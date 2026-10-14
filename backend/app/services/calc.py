"""金额、库存、阶段、计划占用的实时重算。不在旧余额上做增量。"""
from decimal import Decimal

from sqlalchemy.orm import Session

from ..errors import BizError
from ..models import (
    Contract,
    ContractItem,
    ContractOrder,
    ContractStage,
    Goods,
    Invoice,
    InvoiceItem,
    OrderItem,
    PurchasePlan,
    SettleBill,
    Stock,
    WmsBill,
    WmsItem,
    now,
)
from ..money import D, ZERO, allocate, line_ex_tax, line_total, max0, money_str, qty_str, round2
from .util import MSG_ADJUST, q, stamp_new

DEFAULT_RATIOS = [Decimal("30"), Decimal("40"), Decimal("25"), Decimal("5")]


def equipment_name(*sources) -> str:
    for src in sources:
        if src is None:
            continue
        text = src.get("category") if isinstance(src, dict) else getattr(src, "category", None)
        text = (text or "").strip()
        if text:
            return text
    return ""


def plan_of(db: Session, company_id: int, material_code: str) -> PurchasePlan | None:
    code = (material_code or "").strip()
    if not code:
        return None
    return q(db, PurchasePlan, company_id).filter(PurchasePlan.material_code == code).first()


def items_of(db: Session, contract_id: int) -> list[ContractItem]:
    return (
        db.query(ContractItem)
        .filter(ContractItem.contract_id == contract_id, ContractItem.deleted_at.is_(None))
        .order_by(ContractItem.id)
        .all()
    )


def stages_of(db: Session, contract_id: int) -> list[ContractStage]:
    return (
        db.query(ContractStage)
        .filter(ContractStage.contract_id == contract_id, ContractStage.deleted_at.is_(None))
        .order_by(ContractStage.seq, ContractStage.id)
        .all()
    )


def bill_type_for(contract: Contract) -> str:
    return "inbound" if contract.direction == "purchase" else "outbound"


def _wms_rows(db, company_id, *, contract_id=None, warehouse_id=None, material_code=None, bill_type=None):
    query = (
        db.query(WmsItem, WmsBill)
        .join(WmsBill, WmsBill.id == WmsItem.bill_id)
        .filter(
            WmsBill.company_id == company_id,
            WmsBill.deleted_at.is_(None),
            WmsItem.deleted_at.is_(None),
        )
    )
    if contract_id is not None:
        query = query.filter(WmsBill.contract_id == contract_id)
    if warehouse_id is not None:
        query = query.filter(WmsBill.warehouse_id == warehouse_id)
    if material_code is not None:
        query = query.filter(WmsItem.material_code == material_code)
    if bill_type is not None:
        query = query.filter(WmsBill.type == bill_type)
    return query.all()


def moved_qty(db, contract: Contract, material_code: str) -> Decimal:
    rows = _wms_rows(
        db,
        contract.company_id,
        contract_id=contract.id,
        material_code=material_code,
        bill_type=bill_type_for(contract),
    )
    return sum((D(item.qty) for item, _bill in rows), ZERO)


def invoiced_qty(db, contract_id: int, material_code: str) -> Decimal:
    rows = (
        db.query(InvoiceItem.qty)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .filter(
            Invoice.contract_id == contract_id,
            Invoice.deleted_at.is_(None),
            InvoiceItem.deleted_at.is_(None),
            InvoiceItem.material_code == material_code,
        )
        .all()
    )
    return sum((D(r[0]) for r in rows), ZERO)


def invoiced_amount(db, contract_id: int) -> Decimal:
    rows = db.query(Invoice.total).filter(Invoice.contract_id == contract_id, Invoice.deleted_at.is_(None)).all()
    return sum((D(r[0]) for r in rows), ZERO)


def ordered_amount(db, contract_id: int, exclude_order_id: int | None = None) -> Decimal:
    query = db.query(ContractOrder).filter(
        ContractOrder.contract_id == contract_id,
        ContractOrder.deleted_at.is_(None),
    )
    if exclude_order_id:
        query = query.filter(ContractOrder.id != exclude_order_id)
    return sum((D(r.amount) for r in query.all()), ZERO)


def purchased_qty(db, company_id: int, material_code: str, exclude_contract_id: int | None = None) -> Decimal:
    query = (
        db.query(ContractItem.qty)
        .join(Contract, Contract.id == ContractItem.contract_id)
        .filter(
            Contract.company_id == company_id,
            Contract.direction == "purchase",
            Contract.deleted_at.is_(None),
            ContractItem.deleted_at.is_(None),
            ContractItem.material_code == material_code,
        )
    )
    if exclude_contract_id:
        query = query.filter(Contract.id != exclude_contract_id)
    return sum((D(r[0]) for r in query.all()), ZERO)


def realign_header_ex_tax(db):
    """已保存的合同、发票按整单含税金额重算不含税，使两者保持 1+税率。"""
    for contract in db.query(Contract).filter(Contract.deleted_at.is_(None)).all():
        expected = line_ex_tax(contract.amount, contract.tax_rate)
        if D(contract.amount_ex_tax) != expected:
            contract.amount_ex_tax = expected
    invoices = db.query(Invoice).filter(Invoice.deleted_at.is_(None)).all()
    for invoice in invoices:
        items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id, InvoiceItem.deleted_at.is_(None)).all()
        rates = {D(item.tax_rate) for item in items}
        if len(rates) != 1:
            continue
        if any(D(item.amount_ex_tax) != line_ex_tax(item.total, item.tax_rate) for item in items):
            continue
        expected = line_ex_tax(invoice.total, rates.pop())
        if D(invoice.amount_ex_tax) != expected:
            invoice.amount_ex_tax = expected
            invoice.tax = round2(D(invoice.total) - expected)


def refresh_contract_amount(db, contract: Contract):
    rows = items_of(db, contract.id)
    if not rows:
        amount = round2(contract.amount_manual or 0)
        ex_tax = line_ex_tax(amount, contract.tax_rate)
    else:
        amount = ZERO
        for item in rows:
            qty = moved_qty(db, contract, item.material_code) if contract.pricing == "actual" else D(item.qty)
            amount += line_total(qty, item.price)
        amount = round2(amount)
        ex_tax = line_ex_tax(amount, contract.tax_rate)
    contract.amount = amount
    contract.amount_ex_tax = ex_tax
    return amount


def compute_amount_from_payload(contract: Contract, payloads: list[dict], settled_map: dict[str, Decimal]):
    if not payloads:
        amount = round2(contract.amount_manual or 0)
        return amount, line_ex_tax(amount, contract.tax_rate)
    amount = ZERO
    for row in payloads:
        qty = settled_map.get(row["material_code"], ZERO) if contract.pricing == "actual" else D(row["qty"])
        amount += line_total(qty, row["price"])
    amount = round2(amount)
    # 不含税按整单含税金额一次折算，避免逐行四舍五入后再相加，和含税金额偏离 1+税率。
    return amount, line_ex_tax(amount, contract.tax_rate)


def apply_stage_amounts(stages: list[ContractStage], amount: Decimal):
    if not stages:
        return
    weights = [D(s.ratio or 0) for s in stages]
    amounts = allocate(amount, weights)
    if amounts[-1] < 0:
        raise BizError(f"超出 {money_str(-amounts[-1])}")
    for stage, value in zip(stages, amounts):
        stage.plan_amount = value


def assert_stage_sum(stages: list[ContractStage], amount: Decimal):
    total = round2(sum((D(s.plan_amount) for s in stages), ZERO))
    amount = round2(amount)
    if not stages and amount == 0:
        return
    if total != amount:
        diff = total - amount
        word = "超出" if diff > 0 else "相差"
        raise BizError(f"阶段计划金额合计与合同金额{word} {money_str(abs(diff))}")
    for stage in stages:
        if D(stage.plan_amount) < 0:
            raise BizError(f"超出 {money_str(-D(stage.plan_amount))}")


def refresh_settlement(db, contract: Contract):
    stages = stages_of(db, contract.id)
    total = ZERO
    for stage in stages:
        bills = (
            db.query(SettleBill.amount)
            .filter(
                SettleBill.stage_id == stage.id,
                SettleBill.deleted_at.is_(None),
                SettleBill.contract_id == contract.id,
            )
            .all()
        )
        stage.settled_amount = round2(sum((D(b[0]) for b in bills), ZERO))
        total += stage.settled_amount
        if D(stage.settled_amount) < D(stage.plan_amount) or D(stage.plan_amount) <= 0:
            if contract.arrival_stage_id == stage.id:
                stage.arrival_triggered = False
            if contract.ship_stage_id == stage.id:
                stage.ship_triggered = False
    contract.settled_sum = round2(total)
    return contract.settled_sum


def pay_label(direction: str, settled, amount) -> str:
    settled = D(settled)
    amount = D(amount)
    if settled <= 0:
        return "未收" if direction == "sale" else "未付"
    if settled < amount:
        return "部分收款" if direction == "sale" else "部分付款"
    return "已收清" if direction == "sale" else "已付清"


def move_label(direction: str, pairs) -> str:
    """按合同物料数量与已出入库数量判断到货或发货情况。"""
    sale = direction == "sale"
    none_label = "未发货" if sale else "未到货"
    part_label = "部分发货" if sale else "部分到货"
    done_label = "已发货" if sale else "已到货"
    needed = [(D(qty), D(moved)) for qty, moved in pairs if D(qty) > 0]
    if not needed or all(moved <= 0 for _, moved in needed):
        return none_label
    if all(moved >= qty for qty, moved in needed):
        return done_label
    return part_label


def invoice_label(db, contract: Contract) -> str:
    count = db.query(Invoice.id).filter(Invoice.contract_id == contract.id, Invoice.deleted_at.is_(None)).count()
    invoiced = invoiced_amount(db, contract.id)
    if count == 0 and not contract.invoice_locked:
        return "无发票"
    if contract.invoice_locked or invoiced >= D(contract.amount):
        return "已收到"
    return "部分"


def uninvoiced_qty(db, contract: Contract, item: ContractItem) -> Decimal:
    if contract.invoice_locked or invoiced_amount(db, contract.id) > D(contract.amount):
        return ZERO
    return max0(D(item.qty) - invoiced_qty(db, contract.id, item.material_code))


def assert_contract_bounds(db, contract: Contract, new_amount: Decimal, new_qty: dict):
    ordered = ordered_amount(db, contract.id)
    invoiced = invoiced_amount(db, contract.id)
    if round2(new_amount) < ordered or round2(new_amount) < invoiced:
        raise BizError(MSG_ADJUST)
    old_codes = {item.material_code for item in items_of(db, contract.id)}
    for code in old_codes | set(new_qty):
        settled = moved_qty(db, contract, code)
        billed = invoiced_qty(db, contract.id, code)
        qty = new_qty.get(code)
        if qty is None:
            if settled > 0 or billed > 0:
                raise BizError(MSG_ADJUST)
        elif D(qty) < settled or D(qty) < billed:
            raise BizError(MSG_ADJUST)


def assert_plans(db, company_id: int, contract_id: int | None, qty_map: dict):
    if not qty_map:
        return
    codes = sorted(qty_map)
    plans = (
        db.query(PurchasePlan)
        .filter(
            PurchasePlan.company_id == company_id,
            PurchasePlan.material_code.in_(codes),
            PurchasePlan.deleted_at.is_(None),
        )
        .order_by(PurchasePlan.material_code)
        .all()
    )
    plan_map = {p.material_code: p for p in plans}
    missing = [code for code in codes if code not in plan_map]
    if missing:
        raise BizError(f"物料 {'、'.join(missing)} 没有采购计划")
    for code in codes:
        plan = plan_map[code]
        other = purchased_qty(db, company_id, code, exclude_contract_id=contract_id)
        remain = D(plan.qty) - other - D(qty_map[code])
        if remain < 0:
            raise BizError(f"物料 {code} 超出 {qty_str(-remain)}")


def lock_contracts(db, ids):
    ids = sorted({int(i) for i in ids if i})
    if not ids:
        return []
    return db.query(Contract).filter(Contract.id.in_(ids)).order_by(Contract.id).all()


def lock_stages(db, contract_ids):
    if not contract_ids:
        return []
    return (
        db.query(ContractStage)
        .filter(ContractStage.contract_id.in_(list(contract_ids)), ContractStage.deleted_at.is_(None))
        .order_by(ContractStage.id)
        .all()
    )


def lock_plans(db, company_id: int, codes):
    codes = sorted({c for c in codes if c})
    if not codes:
        return []
    return (
        db.query(PurchasePlan)
        .filter(PurchasePlan.company_id == company_id, PurchasePlan.material_code.in_(codes))
        .order_by(PurchasePlan.material_code)
        .all()
    )


def lock_stocks(db, user, company_id: int, keys):
    keys = sorted({(int(w), c) for w, c in keys if c})
    if not keys:
        return
    codes = sorted({c for _, c in keys})
    db.query(Goods).filter(Goods.company_id == company_id, Goods.material_code.in_(codes)).order_by(Goods.material_code).all()
    for warehouse_id, code in keys:
        row = (
            db.query(Stock)
            .filter_by(company_id=company_id, warehouse_id=warehouse_id, material_code=code)
            .first()
        )
        if row is None:
            row = Stock(
                company_id=company_id,
                warehouse_id=warehouse_id,
                material_code=code,
                goods_code=code,
                qty=Decimal("0"),
                version=1,
                created_by=user.employee_id,
                updated_by=user.employee_id,
                created_at=now(),
                updated_at=now(),
            )
            db.add(row)
    db.flush()


def recalc_stock(db, company_id: int, warehouse_id: int, material_code: str):
    inbound = _wms_rows(db, company_id, warehouse_id=warehouse_id, material_code=material_code, bill_type="inbound")
    outbound = _wms_rows(db, company_id, warehouse_id=warehouse_id, material_code=material_code, bill_type="outbound")
    qty = sum((D(item.qty) for item, _ in inbound), ZERO) - sum((D(item.qty) for item, _ in outbound), ZERO)
    if qty < 0:
        raise BizError(f"库存不足，物料 {material_code} 超出 {qty_str(-qty)}")
    cost = None
    if inbound:
        best = max(inbound, key=lambda pair: (pair[1].bill_date, pair[1].created_at or now(), pair[1].id))
        cost = D(best[0].price)
    row = db.query(Stock).filter_by(company_id=company_id, warehouse_id=warehouse_id, material_code=material_code).first()
    goods = q(db, Goods, company_id).filter(Goods.material_code == material_code).first()
    if row is None:
        row = Stock(company_id=company_id, warehouse_id=warehouse_id, material_code=material_code, version=1)
        db.add(row)
    row.qty = qty
    row.cost = cost
    row.goods_code = material_code
    row.goods_name = goods.name if goods else material_code
    row.unit = goods.unit if goods else None
    row.deleted_at = None
    row.deleted_by = None
    return row


def after_stock_touch_contracts(db, contracts: list[Contract]):
    for contract in contracts:
        if contract.pricing != "actual":
            continue
        new_amount = refresh_contract_amount(db, contract)
        ordered = ordered_amount(db, contract.id)
        if ordered > new_amount:
            raise BizError("请先调整订单")
        invoiced = invoiced_amount(db, contract.id)
        contract.invoice_locked = invoiced > new_amount
        stages = stages_of(db, contract.id)
        if stages:
            apply_stage_amounts(stages, new_amount)
            assert_stage_sum(stages, new_amount)


def order_items(db, order_id: int):
    return (
        db.query(OrderItem)
        .filter(OrderItem.order_id == order_id, OrderItem.deleted_at.is_(None))
        .order_by(OrderItem.id)
        .all()
    )


def arrival_text(name: str, unit: str, moved: Decimal, qty: Decimal, sale: bool) -> str:
    if D(moved) >= D(qty):
        return "发齐" if sale else "到齐"
    verb = "已经发货" if sale else "已经到货"
    return f"{name or ''}{verb}{qty_str(moved)}{unit or ''}"


def default_stage_specs(direction: str):
    names = ["预收款", "进度款", "验收款", "质保金"] if direction == "sale" else ["预付款", "进度款", "验收款", "质保金"]
    return list(zip(names, DEFAULT_RATIOS))


def make_default_stages(user, company_id, contract, amount, dates):
    specs = default_stage_specs(contract.direction)
    amounts = allocate(amount, [ratio for _, ratio in specs])
    if amounts and amounts[-1] < 0:
        raise BizError(f"超出 {money_str(-amounts[-1])}")
    rows = []
    for index, ((name, ratio), money) in enumerate(zip(specs, amounts), start=1):
        plan_date = dates[index - 1] if index - 1 < len(dates) else None
        stage = ContractStage(
            contract_id=contract.id,
            seq=index,
            name=name,
            ratio=ratio,
            plan_amount=money,
            plan_date=plan_date,
            settled_amount=Decimal("0"),
            arrival_triggered=False,
            ship_triggered=False,
        )
        stamp_new(stage, user, company_id)
        rows.append(stage)
    return rows
