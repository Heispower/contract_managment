"""合同、订单、出入库、收付款、发票的保存与删除。"""
from decimal import Decimal

from ..errors import BizError
from ..models import (
    Contract,
    ContractItem,
    ContractOrder,
    ContractStage,
    FundAccount,
    Invoice,
    InvoiceItem,
    OrderItem,
    Party,
    PartyContact,
    Project,
    SettleBill,
    SysUser,
    SysUserCompany,
    Warehouse,
    WmsBill,
    WmsItem,
    now,
)
from ..money import D, ZERO, back_calc_from_ex_tax, line_ex_tax, line_tax, line_total, money_str, price_ex_tax_display, qty_str, round2, split_line
from . import calc
from .refs import refuse_contract, refuse_stage
from .util import (
    MSG_ADJUST,
    MSG_CLOSE,
    MSG_CODE,
    MSG_DIRECTION,
    MSG_NOT_SIGNED,
    MSG_PERM,
    bump,
    ensure_code_free,
    ensure_creator,
    ensure_version,
    get_row,
    next_contract_code,
    next_daily_code,
    next_order_code,
    next_supplement_code,
    op_log,
    parse_date,
    q,
    soft_delete,
    stamp_new,
)

CONTRACT_FLOW = {
    "未签订": {"未签订", "已签订", "已终止"},
    "已签订": {"已签订", "已终止"},
    "已终止": {"已终止"},
}


def link_project(db, user, company_id, payload) -> int:
    project_id = payload.get("project_id")
    if not project_id:
        raise BizError("请选择项目")
    project = get_row(db, Project, int(project_id), company_id)
    items = payload.get("items") or []
    if not items:
        raise BizError("请先勾选合同")
    for item in items:
        row = get_row(db, Contract, int(item.get("id")), company_id)
        ensure_creator(row, user, supplement=row.nature == "supplement")
        ensure_version(row, item.get("version"))
        row.project_id = project.id
        bump(row, user.employee_id)
        op_log(db, user, company_id, "关联项目", "contract", row.id, {"code": row.contract_code, "project": project.project_code})
    return len(items)


def _party(db, company_id, party_id) -> Party:
    if not party_id:
        raise BizError("请选择客商")
    party = get_row(db, Party, party_id, company_id)
    return party


def _owner_ok(db, company_id, owner_id, previous=None):
    if previous and previous == owner_id:
        user = db.query(SysUser).filter(SysUser.employee_id == owner_id, SysUser.deleted_at.is_(None)).first()
        if not user:
            raise BizError("业务员不存在")
        return user
    user = db.query(SysUser).filter(SysUser.employee_id == owner_id, SysUser.deleted_at.is_(None)).first()
    if not user or user.status != "启用":
        raise BizError("业务员不存在或已停用")
    if user.is_super_admin:
        return user
    rel = (
        db.query(SysUserCompany)
        .filter(SysUserCompany.employee_id == owner_id, SysUserCompany.company_id == company_id)
        .first()
    )
    if not rel:
        raise BizError("业务员不存在或已停用")
    return user


def _direction_party(direction, party: Party):
    expect = "customer" if direction == "sale" else "supplier"
    if party.type != expect:
        raise BizError(MSG_DIRECTION)


def _normalize_items(raw_items):
    rows = []
    seen = set()
    for raw in raw_items or []:
        code = (raw.get("material_code") or "").strip()
        if not code:
            raise BizError("物料编号不能为空")
        if code in seen:
            raise BizError(f"物料 {code} 重复")
        seen.add(code)
        qty = D(raw.get("qty"))
        price = D(raw.get("price"))
        if qty <= 0:
            raise BizError("数量必须大于 0")
        if price < 0:
            raise BizError("含税单价不能小于 0")
        rows.append(
            {
                "material_code": code,
                "name_cn": raw.get("name_cn") or "",
                "name_en": raw.get("name_en") or "",
                "spec": raw.get("spec") or "",
                "unit": raw.get("unit") or "",
                "qty": qty,
                "price": round2(price),
                "plan_no": raw.get("plan_no") or None,
                "plan_row": raw.get("plan_row"),
                "category": (raw.get("category") or "").strip() or None,
                "remark": raw.get("remark") or "",
            }
        )
    return rows


def _fill_party_snapshot(db, contract: Contract, party: Party):
    contract.party_id = party.id
    contract.party_name = party.name
    contract.party_tax_no = party.tax_no
    contract.party_invoice_title = party.invoice_title
    contract.party_invoice_phone = party.invoice_phone
    contract.party_invoice_address = party.invoice_address
    contract.party_address = party.address
    contract.party_bank_name = party.bank_name
    contract.party_account_name = party.account_name
    contract.party_bank_account = party.bank_account
    contract.party_bank_branch = party.bank_branch
    contract.party_legal_name = party.legal_name
    contract.party_agent = party.agent_name
    contact = (
        db.query(PartyContact)
        .filter(
            PartyContact.party_id == party.id,
            PartyContact.deleted_at.is_(None),
            PartyContact.is_default.is_(True),
        )
        .first()
    )
    contract.contact_name = contact.name if contact else None
    contract.contact_phone = contact.phone if contact else None
    if contract.direction == "sale":
        contract.ship_address = party.address


def _sync_items(db, user, company_id, contract, payloads):
    existing = (
        db.query(ContractItem)
        .filter(ContractItem.contract_id == contract.id, ContractItem.deleted_at.is_(None))
        .all()
    )
    by_code = {row.material_code: row for row in existing}
    keep = set()
    for payload in payloads:
        keep.add(payload["material_code"])
        row = by_code.get(payload["material_code"])
        if row is None:
            row = ContractItem(contract_id=contract.id)
            stamp_new(row, user, company_id)
            db.add(row)
        else:
            bump(row, user.employee_id)
        row.material_code = payload["material_code"]
        row.name_cn = payload["name_cn"]
        row.name_en = payload["name_en"]
        row.spec = payload["spec"]
        row.unit = payload["unit"]
        row.qty = payload["qty"]
        row.price = payload["price"]
        row.plan_no = payload["plan_no"]
        row.plan_row = payload["plan_row"]
        row.category = payload.get("category") or None
        row.remark = payload["remark"]
    for code, row in by_code.items():
        if code not in keep:
            soft_delete(row, user.employee_id)
    db.flush()


def _sync_stages(db, user, company_id, contract, payloads):
    existing = (
        db.query(ContractStage)
        .filter(ContractStage.contract_id == contract.id, ContractStage.deleted_at.is_(None))
        .all()
    )
    by_id = {row.id: row for row in existing}
    keep = set()
    ordered = []
    for index, raw in enumerate(payloads, start=1):
        stage_id = raw.get("id")
        row = by_id.get(int(stage_id)) if stage_id else None
        if row is None:
            row = ContractStage(contract_id=contract.id, arrival_triggered=False, ship_triggered=False, settled_amount=Decimal("0"))
            stamp_new(row, user, company_id)
            db.add(row)
        else:
            keep.add(row.id)
            bump(row, user.employee_id)
        row.seq = index
        row.name = (raw.get("name") or "").strip()
        if not row.name:
            raise BizError("阶段名称不能为空")
        row.ratio = D(raw.get("ratio") or 0)
        row.plan_amount = round2(raw.get("plan_amount") or 0)
        row.plan_date = parse_date(raw.get("plan_date"))
        row.remark = raw.get("remark") or ""
        ordered.append(row)
    for stage_id, row in by_id.items():
        if stage_id in keep:
            continue
        refuse_stage(db, row.id)
        soft_delete(row, user.employee_id)
    db.flush()
    return [row for row in ordered if row.deleted_at is None]


def _point_round(contract, stages, arrival_index, ship_index):
    if not stages:
        contract.arrival_stage_id = None
        contract.ship_stage_id = None
        return
    if contract.direction == "purchase":
        index = 0 if arrival_index is None else int(arrival_index)
        index = min(max(index, 0), len(stages) - 1)
        contract.arrival_stage_id = stages[index].id
        contract.ship_stage_id = None
    else:
        index = 0 if ship_index is None else int(ship_index)
        index = min(max(index, 0), len(stages) - 1)
        contract.ship_stage_id = stages[index].id
        contract.arrival_stage_id = None


def save_contract(db, user, company_id, payload, contract: Contract | None = None, as_import: bool = False):
    direction = payload.get("direction") or (contract.direction if contract else None)
    if direction not in ("sale", "purchase"):
        raise BizError(MSG_DIRECTION)
    if contract and contract.direction != direction:
        raise BizError(MSG_DIRECTION)
    nature = payload.get("nature") or (contract.nature if contract else "main")
    if contract and contract.nature != nature:
        raise BizError("合同性质创建后不可改")
    party = _party(db, company_id, payload.get("party_id"))
    if party.status != "启用" and (not contract or contract.party_id != party.id):
        raise BizError("客商已停用")
    _direction_party(direction, party)
    previous_owner = contract.owner_id if contract else None
    owner = _owner_ok(db, company_id, payload.get("owner_id"), previous_owner)
    status = payload.get("status") or "已签订"
    if contract:
        allowed = CONTRACT_FLOW.get(contract.status, {contract.status})
        if status not in allowed:
            raise BizError("状态不允许这样变更")
        if not as_import:
            ensure_creator(contract, user, supplement=contract.nature == "supplement")
        ensure_version(contract, payload.get("version"))
        calc.lock_contracts(db, [contract.id])
    else:
        if status not in ("未签订", "已签订", "已终止"):
            raise BizError("状态不允许这样变更")

    allocated = None
    code = (payload.get("contract_code") or "").strip()
    if contract is None:
        if not code:
            if nature == "supplement":
                parent = get_row(db, Contract, payload.get("parent_contract_id"), company_id)
                root = _root_contract(db, company_id, parent)
                code = next_supplement_code(db, company_id, root.contract_code)
                payload["parent_contract_id"] = root.id
            elif direction == "purchase":
                from .numbering import take_purchase_number
                allocated = take_purchase_number(db, company_id, payload)
                code = allocated["number"]
            else:
                code = next_contract_code(db, company_id, direction)
        ensure_code_free(db, Contract, company_id, Contract.contract_code, code)
    elif code and code != contract.contract_code:
        ensure_code_free(db, Contract, company_id, Contract.contract_code, code, contract.id)

    items = _normalize_items(payload.get("items"))
    if payload.get("generated_from"):
        _assert_generated_items(db, company_id, payload["generated_from"], items)

    creating = contract is None
    if creating:
        contract = Contract(archived=False, invoice_locked=False, settled_sum=Decimal("0"))
        stamp_new(contract, user, company_id)
        db.add(contract)
    contract.contract_code = code or contract.contract_code
    contract.name = (payload.get("name") or "").strip()
    if not contract.name:
        raise BizError("合同名称不能为空")
    contract.nature = nature
    contract.direction = direction
    contract.type_name = payload.get("type_name") or None
    contract.owner_id = owner.employee_id
    contract.status = status
    contract.archived = False
    project_id = payload.get("project_id") or None
    if project_id:
        get_row(db, Project, project_id, company_id)
    contract.project_id = int(project_id) if project_id else None
    contract.sign_date = parse_date(payload.get("sign_date"))
    if "start_date" in payload:
        contract.start_date = parse_date(payload.get("start_date"))
    if "end_date" in payload:
        contract.end_date = parse_date(payload.get("end_date"))
    pricing = payload.get("pricing") or "fixed"
    if pricing not in ("fixed", "actual"):
        raise BizError("计价方式不正确")
    contract.pricing = pricing
    contract.tax_rate = D(payload.get("tax_rate") if payload.get("tax_rate") not in (None, "") else 13)
    contract.amount_manual = round2(payload.get("amount_manual") or 0) if not items else None
    contract.content = payload.get("content") or ""
    contract.terms = payload.get("terms") or ""
    contract.remark = payload.get("remark") or ""
    if nature == "supplement":
        parent_id = payload.get("parent_contract_id") or contract.parent_contract_id
        parent = get_row(db, Contract, parent_id, company_id)
        root = _root_contract(db, company_id, parent)
        if root.direction != direction:
            raise BizError(MSG_DIRECTION)
        if contract.id and root.id == contract.id:
            raise BizError("不能选择自己作为原合同")
        contract.parent_contract_id = root.id
    else:
        contract.parent_contract_id = None
    party_changed = creating or contract.party_id != party.id
    if creating or party_changed:
        _fill_party_snapshot(db, contract, party)
    for key in ("subject_name", "transport_mode", "delivery_term", "freight_bearer", "receiver_name", "acceptance_text", "annex_note", "party_legal_name", "party_agent"):
        if key in payload:
            setattr(contract, key, payload.get(key) or "")
    if direction == "purchase" and "ship_address" in payload:
        contract.ship_address = payload.get("ship_address") or ""
    db.flush()

    settled_map = {row["material_code"]: calc.moved_qty(db, contract, row["material_code"]) for row in items}
    amount, ex_tax = calc.compute_amount_from_payload(contract, items, settled_map)
    if not creating:
        calc.assert_contract_bounds(db, contract, amount, {row["material_code"]: row["qty"] for row in items})
    if direction == "purchase":
        codes = [row["material_code"] for row in items]
        if not creating:
            codes += [row.material_code for row in calc.items_of(db, contract.id)]
        calc.lock_plans(db, company_id, codes)
        calc.assert_plans(db, company_id, None if creating else contract.id, {row["material_code"]: row["qty"] for row in items})

    contract.amount = amount
    contract.amount_ex_tax = ex_tax
    _sync_items(db, user, company_id, contract, items)

    stage_payload = payload.get("stages")
    if payload.get("keep_stages") and not creating:
        stages = calc.stages_of(db, contract.id)
        if not stages:
            dates = [contract.sign_date, contract.start_date, contract.end_date, contract.end_date]
            stages = calc.make_default_stages(user, company_id, contract, amount, dates)
            for stage in stages:
                db.add(stage)
            db.flush()
        else:
            calc.apply_stage_amounts(stages, amount)
        calc.assert_stage_sum(calc.stages_of(db, contract.id), amount)
    elif creating and not stage_payload:
        dates = [contract.sign_date, contract.start_date, contract.end_date, contract.end_date]
        stages = calc.make_default_stages(user, company_id, contract, amount, dates)
        for stage in stages:
            db.add(stage)
        db.flush()
    else:
        stages = _sync_stages(db, user, company_id, contract, stage_payload or [])
        if payload.get("realloc_stages"):
            calc.apply_stage_amounts(stages, amount)
        calc.assert_stage_sum(stages, amount)
    stages = calc.stages_of(db, contract.id)
    _point_round(contract, stages, payload.get("arrival_index"), payload.get("ship_index"))
    if not creating:
        bump(contract, user.employee_id)
    calc.refresh_settlement(db, contract)
    op_log(db, user, company_id, "修改" if not creating else "新增", "contract", contract.id, {"code": contract.contract_code, "amount": money_str(contract.amount)})
    if direction == "purchase" and contract.nature == "main":
        from .numbering import sync_purchase_contract
        sync_purchase_contract(db, user, company_id, contract, payload or {}, allocated)
    db.flush()
    return contract


def _root_contract(db, company_id, contract: Contract) -> Contract:
    seen = set()
    current = contract
    while current.nature == "supplement" and current.parent_contract_id and current.id not in seen:
        seen.add(current.id)
        current = get_row(db, Contract, current.parent_contract_id, company_id)
    return current


def _assert_generated_items(db, company_id, source_ids, items):
    merged = {}
    for cid in source_ids:
        contract = get_row(db, Contract, cid, company_id)
        if contract.direction != "purchase":
            raise BizError(MSG_DIRECTION)
        for row in calc.items_of(db, contract.id):
            slot = merged.setdefault(row.material_code, Decimal("0"))
            merged[row.material_code] = slot + D(row.qty)
    got = {row["material_code"]: D(row["qty"]) for row in items}
    if set(got) - set(merged):
        raise BizError("此模式只能删除物料，不能新增物料")
    for code, qty in got.items():
        if qty != merged.get(code):
            raise BizError("数量必须仍是采购合同带来的数量")


def delete_contract(db, user, company_id, contract: Contract):
    ensure_creator(contract, user, supplement=contract.nature == "supplement")
    children = (
        q(db, Contract, company_id)
        .filter(Contract.parent_contract_id == contract.id, Contract.nature == "supplement")
        .first()
    )
    if children:
        raise BizError("请先删除其补充协议")
    refuse_contract(db, company_id, contract.id)
    if contract.direction == "purchase" and contract.nature == "main":
        from .numbering import detach_purchase_contract
        detach_purchase_contract(db, user, company_id, contract)
    soft_delete(contract, user.employee_id)
    for row in calc.items_of(db, contract.id):
        soft_delete(row, user.employee_id)
    for row in calc.stages_of(db, contract.id):
        soft_delete(row, user.employee_id)
    op_log(db, user, company_id, "删除", "contract", contract.id, {"code": contract.contract_code})


def supplement_prefill(db, company_id, contract: Contract):
    root = _root_contract(db, company_id, contract)
    return {
        "nature": "supplement",
        "parent_contract_id": root.id,
        "parent_code": root.contract_code,
        "contract_code": next_supplement_code(db, company_id, root.contract_code),
        "direction": root.direction,
        "type_name": root.type_name,
        "party_id": root.party_id,
        "owner_id": root.owner_id,
        "tax_rate": str(root.tax_rate),
        "pricing": "fixed",
        "status": "已签订",
    }


def merge_sale_prefill(db, company_id, ids):
    merged = {}
    order = []
    for cid in ids:
        contract = get_row(db, Contract, cid, company_id)
        if contract.direction != "purchase":
            raise BizError(MSG_DIRECTION)
        if contract.status != "已签订":
            raise BizError(MSG_NOT_SIGNED)
        for row in calc.items_of(db, contract.id):
            if row.material_code not in merged:
                order.append(row.material_code)
                merged[row.material_code] = {
                    "material_code": row.material_code,
                    "name_cn": row.name_cn,
                    "name_en": row.name_en,
                    "spec": row.spec,
                    "unit": row.unit,
                    "qty": ZERO,
                    "amount": ZERO,
                }
            bucket = merged[row.material_code]
            qty = D(row.qty)
            bucket["qty"] += qty
            bucket["amount"] += qty * D(row.price)
    items = []
    for code in order:
        row = merged[code]
        qty = row["qty"]
        cost = round2(row["amount"] / qty) if qty else ZERO
        price = round2(cost * Decimal("1.10"))
        items.append({
            "material_code": row["material_code"],
            "name_cn": row["name_cn"],
            "name_en": row["name_en"],
            "spec": row["spec"],
            "unit": row["unit"],
            "qty": format(qty, "f"),
            "cost": money_str(cost),
            "price": money_str(price),
        })
    return {"direction": "sale", "nature": "main", "pricing": "fixed", "status": "已签订", "tax_rate": "13", "markup": "10", "generated_from": ids, "items": items, "stages": []}


def wms_prefill(db, company_id, contract: Contract, bill_type: str):
    if contract.status != "已签订":
        raise BizError(MSG_NOT_SIGNED)
    expect = "inbound" if contract.direction == "purchase" else "outbound"
    if bill_type != expect:
        raise BizError(MSG_DIRECTION)
    items = []
    for row in calc.items_of(db, contract.id):
        moved = calc.moved_qty(db, contract, row.material_code)
        remain = D(row.qty) - moved
        if remain <= 0:
            continue
        items.append(
            {
                "material_code": row.material_code,
                "name_cn": row.name_cn,
                "spec": row.spec,
                "unit": row.unit,
                "qty": format(remain, "f"),
                "price": format(D(row.price), "f"),
            }
        )
    return {
        "type": bill_type,
        "contract_id": contract.id,
        "contract_code": contract.contract_code,
        "party_id": contract.party_id,
        "party_name": contract.party_name,
        "items": items,
        "saved": False,
    }


def input_invoice_prefill(db, company_id, contract: Contract):
    if contract.direction != "purchase":
        raise BizError(MSG_DIRECTION)
    if contract.status != "已签订":
        raise BizError(MSG_NOT_SIGNED)
    if contract.invoice_locked:
        raise BizError("已开票金额超出合同金额，禁止继续开票")
    party = _party(db, company_id, contract.party_id)
    items = []
    for row in calc.items_of(db, contract.id):
        remain = calc.uninvoiced_qty(db, contract, row)
        if remain <= 0:
            continue
        items.append({
            "material_code": row.material_code,
            "name_cn": row.name_cn,
            "spec": row.spec or "",
            "unit": row.unit or "",
            "qty": qty_str(remain),
            "price": format(D(row.price), "f"),
            "tax_rate": format(D(contract.tax_rate), "f"),
            "manual_tax": False,
        })
    if not items:
        raise BizError("该合同没有未开票数量，无法生成进项发票")
    return {
        "direction": "input",
        "contract_id": contract.id,
        "contract_code": contract.contract_code,
        "party_id": party.id,
        "party_name": party.invoice_title or party.name,
        "party_tax_no": party.tax_no or "",
        "invoice_type": "增值税专用发票",
        "tax_rate": format(D(contract.tax_rate), "f"),
        "items": items,
        "saved": False,
    }


def _active_order(db, company_id, contract_id, exclude_id=None):
    query = q(db, ContractOrder, company_id).filter(ContractOrder.contract_id == contract_id)
    if exclude_id:
        query = query.filter(ContractOrder.id != exclude_id)
    return query.first()


def _order_amount(items):
    return round2(sum((line_total(row["qty"], row["price"]) for row in items), ZERO))


def _write_order_items(db, user, company_id, order, items):
    existing = (
        db.query(OrderItem).filter(OrderItem.order_id == order.id, OrderItem.deleted_at.is_(None)).all()
    )
    by_code = {row.material_code: row for row in existing}
    keep = set()
    for payload in items:
        keep.add(payload["material_code"])
        row = by_code.get(payload["material_code"])
        if row is None:
            row = OrderItem(order_id=order.id)
            stamp_new(row, user, company_id)
            db.add(row)
        else:
            bump(row, user.employee_id)
        row.material_code = payload["material_code"]
        row.name_cn = payload["name_cn"]
        row.spec = payload["spec"]
        row.unit = payload["unit"]
        row.qty = payload["qty"]
        row.price = payload["price"]
        row.remark = payload.get("remark") or ""
    for code, row in by_code.items():
        if code not in keep:
            soft_delete(row, user.employee_id)


def save_order(db, user, company_id, payload, order: ContractOrder | None = None):
    contract = get_row(db, Contract, payload.get("contract_id"), company_id)
    if contract.status != "已签订":
        raise BizError(MSG_NOT_SIGNED)
    direction = payload.get("direction") or contract.direction
    if direction != contract.direction:
        raise BizError(MSG_DIRECTION)
    if not calc.items_of(db, contract.id):
        raise BizError("请先回合同维护物料")
    items = _normalize_items(payload.get("items"))
    if not items:
        raise BizError("请先回合同维护物料")
    amount = _order_amount(items)
    calc.lock_contracts(db, [contract.id] + ([order.contract_id] if order else []))
    if order:
        ensure_creator(order, user)
        ensure_version(order, payload.get("version"))
        if order.contract_id != contract.id:
            return _switch_order_contract(db, user, company_id, order, contract, items, payload)
        other = calc.ordered_amount(db, contract.id, exclude_order_id=order.id)
        if amount > D(contract.amount) - other:
            raise BizError(f"超出 {money_str(amount - (D(contract.amount) - other))}")
        if _active_order(db, company_id, contract.id, exclude_id=order.id):
            raise BizError("该合同已有订单")
        order.party_id = contract.party_id
        order.tax_rate = contract.tax_rate
        order.owner_id = contract.owner_id
        order.direction = contract.direction
        order.remark = payload.get("remark") or contract.content or ""
        order.amount = amount
        _write_order_items(db, user, company_id, order, items)
        bump(order, user.employee_id)
        op_log(db, user, company_id, "修改", "order", order.id, {"code": order.order_code, "amount": money_str(amount)})
        return order
    if _active_order(db, company_id, contract.id):
        raise BizError("该合同已有订单")
    if amount > D(contract.amount):
        raise BizError(f"超出 {money_str(amount - D(contract.amount))}")
    code = (payload.get("order_code") or "").strip() or next_order_code(db, company_id, contract.contract_code)
    ensure_code_free(db, ContractOrder, company_id, ContractOrder.order_code, code)
    order = ContractOrder(
        order_code=code,
        contract_id=contract.id,
        direction=contract.direction,
        party_id=contract.party_id,
        tax_rate=contract.tax_rate,
        owner_id=contract.owner_id,
        status="open",
        remark=payload.get("remark") or contract.content or "",
        amount=amount,
    )
    stamp_new(order, user, company_id)
    db.add(order)
    db.flush()
    _write_order_items(db, user, company_id, order, items)
    op_log(db, user, company_id, "新增", "order", order.id, {"code": order.order_code})
    return order


def _switch_order_contract(db, user, company_id, order, contract, items, payload):
    if contract.status != "已签订":
        raise BizError(MSG_NOT_SIGNED)
    if _active_order(db, company_id, contract.id):
        raise BizError("该合同已有订单")
    amount = _order_amount(items)
    if amount > D(contract.amount):
        raise BizError(f"超出 {money_str(amount - D(contract.amount))}")
    old_code = order.order_code
    soft_delete(order, user.employee_id)
    for row in calc.order_items(db, order.id):
        soft_delete(row, user.employee_id)
    db.flush()
    code = next_order_code(db, company_id, contract.contract_code)
    created = ContractOrder(
        order_code=code,
        contract_id=contract.id,
        direction=contract.direction,
        party_id=contract.party_id,
        tax_rate=contract.tax_rate,
        owner_id=contract.owner_id,
        status="open",
        remark=payload.get("remark") or contract.content or "",
        amount=amount,
    )
    stamp_new(created, user, company_id)
    db.add(created)
    db.flush()
    _write_order_items(db, user, company_id, created, items)
    op_log(db, user, company_id, "修改", "order", created.id, {"old_code": old_code, "code": code, "switch": True})
    return created


def delete_order(db, user, company_id, order: ContractOrder):
    ensure_creator(order, user)
    soft_delete(order, user.employee_id)
    for row in calc.order_items(db, order.id):
        soft_delete(row, user.employee_id)
    op_log(db, user, company_id, "删除", "order", order.id, {"code": order.order_code})


def close_order(db, user, company_id, order: ContractOrder, version, reopen=False):
    ensure_creator(order, user)
    ensure_version(order, version)
    contract = get_row(db, Contract, order.contract_id, company_id)
    if not reopen:
        if order.status == "closed":
            return order
        sale = order.direction == "sale"
        for row in calc.order_items(db, order.id):
            moved = calc.moved_qty(db, contract, row.material_code)
            if moved < D(row.qty):
                raise BizError(MSG_CLOSE)
        order.status = "closed"
    else:
        order.status = "open"
    bump(order, user.employee_id)
    op_log(db, user, company_id, "取消关闭" if reopen else "关闭", "order", order.id, {"code": order.order_code})
    return order


def _warehouse(db, company_id, warehouse_id, current=None):
    row = get_row(db, Warehouse, warehouse_id, company_id)
    if row.status != "启用" and row.id != current:
        raise BizError("仓库已停用")
    return row


def save_wms(db, user, company_id, payload, bill: WmsBill | None = None):
    contract = get_row(db, Contract, payload.get("contract_id"), company_id)
    bill_type = payload.get("type") or (bill.type if bill else None)
    expect = "inbound" if contract.direction == "purchase" else "outbound"
    if bill_type != expect:
        raise BizError(MSG_DIRECTION)
    if bill is None and contract.status != "已签订":
        raise BizError(MSG_NOT_SIGNED)
    if bill and bill.type != bill_type:
        raise BizError(MSG_DIRECTION)
    warehouse = _warehouse(db, company_id, payload.get("warehouse_id"), bill.warehouse_id if bill else None)
    items = _normalize_items(payload.get("items"))
    if not items:
        raise BizError("请保留至少一行到货或发货明细")
    contract_items = {row.material_code: row for row in calc.items_of(db, contract.id)}
    for row in items:
        if row["material_code"] not in contract_items:
            raise BizError(f"物料 {row['material_code']} 不在合同中")
    old_contract_id = bill.contract_id if bill else None
    old_warehouse = bill.warehouse_id if bill else None
    contract_ids = [contract.id] + ([old_contract_id] if old_contract_id else [])
    calc.lock_contracts(db, contract_ids)
    calc.lock_stages(db, contract_ids)
    keys = [(warehouse.id, row["material_code"]) for row in items]
    if bill:
        ensure_creator(bill, user)
        ensure_version(bill, payload.get("version"))
        old_items = db.query(WmsItem).filter(WmsItem.bill_id == bill.id, WmsItem.deleted_at.is_(None)).all()
        keys += [(old_warehouse, row.material_code) for row in old_items]
    calc.lock_stocks(db, user, company_id, keys)

    creating = bill is None
    if creating:
        code = (payload.get("bill_code") or "").strip() or next_daily_code(
            db, WmsBill, company_id, WmsBill.bill_code, "RK" if bill_type == "inbound" else "CK"
        )
        ensure_code_free(db, WmsBill, company_id, WmsBill.bill_code, code)
        bill = WmsBill(type=bill_type)
        stamp_new(bill, user, company_id)
        db.add(bill)
    else:
        code = (payload.get("bill_code") or bill.bill_code).strip()
        if code != bill.bill_code:
            ensure_code_free(db, WmsBill, company_id, WmsBill.bill_code, code, bill.id)
    bill.bill_code = code
    bill.bill_date = parse_date(payload.get("bill_date")) or now().date()
    bill.type = bill_type
    bill.contract_id = contract.id
    bill.party_id = contract.party_id
    bill.party_name = contract.party_name
    bill.warehouse_id = warehouse.id
    bill.remark = payload.get("remark") or ""
    db.flush()
    _sync_wms_items(db, user, company_id, bill, items, contract_items)
    db.flush()
    if bill.type == "inbound":
        from . import customs
        customs.sync_from_wms(db, user, company_id, bill)
    _assert_wms_qty(db, contract, items)
    if old_contract_id and old_contract_id != contract.id:
        old_contract = get_row(db, Contract, old_contract_id, company_id)
        _assert_wms_qty(db, old_contract, [])
    touched = {(warehouse.id, row["material_code"]) for row in items}
    if old_warehouse:
        old_rows = db.query(WmsItem).filter(WmsItem.bill_id == bill.id).all()
        for row in old_rows:
            touched.add((old_warehouse, row.material_code))
        if old_warehouse != warehouse.id:
            for row in items:
                touched.add((old_warehouse, row["material_code"]))
    for wh, code in sorted(touched):
        calc.recalc_stock(db, company_id, wh, code)
    contracts = calc.lock_contracts(db, contract_ids)
    calc.after_stock_touch_contracts(db, [c for c in contracts if c.deleted_at is None])
    if not creating:
        bump(bill, user.employee_id)
    op_log(db, user, company_id, "修改" if not creating else "新增", "wms", bill.id, {"code": bill.bill_code, "type": bill.type})
    return bill


def _sync_wms_items(db, user, company_id, bill, items, contract_items):
    existing = db.query(WmsItem).filter(WmsItem.bill_id == bill.id, WmsItem.deleted_at.is_(None)).all()
    by_code = {row.material_code: row for row in existing}
    keep = set()
    for payload in items:
        keep.add(payload["material_code"])
        src = contract_items[payload["material_code"]]
        row = by_code.get(payload["material_code"])
        if row is None:
            row = WmsItem(bill_id=bill.id)
            stamp_new(row, user, company_id)
            db.add(row)
        else:
            bump(row, user.employee_id)
        row.material_code = payload["material_code"]
        row.name_cn = payload["name_cn"] or src.name_cn
        row.spec = payload["spec"] or src.spec
        row.unit = payload["unit"] or src.unit
        row.qty = payload["qty"]
        row.price = payload["price"] if payload["price"] else src.price
        row.amount = line_total(row.qty, row.price)
        row.category = payload.get("category") or getattr(src, "category", None) or ""
        row.remark = payload.get("remark") or ""
    for code, row in by_code.items():
        if code not in keep:
            soft_delete(row, user.employee_id)


def _assert_wms_qty(db, contract: Contract, _items):
    for row in calc.items_of(db, contract.id):
        moved = calc.moved_qty(db, contract, row.material_code)
        if moved > D(row.qty):
            raise BizError(f"物料 {row.material_code} 超出 {format(moved - D(row.qty), 'f')}")


def delete_wms(db, user, company_id, bill: WmsBill):
    ensure_creator(bill, user)
    if bill.type == "inbound":
        from . import customs
        customs.unlink_wms(db, user, company_id, bill)
    contract = get_row(db, Contract, bill.contract_id, company_id)
    items = db.query(WmsItem).filter(WmsItem.bill_id == bill.id, WmsItem.deleted_at.is_(None)).all()
    calc.lock_contracts(db, [contract.id])
    calc.lock_stages(db, [contract.id])
    calc.lock_stocks(db, user, company_id, [(bill.warehouse_id, row.material_code) for row in items])
    soft_delete(bill, user.employee_id)
    for row in items:
        soft_delete(row, user.employee_id)
    db.flush()
    for row in items:
        calc.recalc_stock(db, company_id, bill.warehouse_id, row.material_code)
    calc.after_stock_touch_contracts(db, [contract])
    op_log(db, user, company_id, "删除", "wms", bill.id, {"code": bill.bill_code})


def _stage_remaining(stage: ContractStage):
    return round2(D(stage.plan_amount) - D(stage.settled_amount))


def save_settle_many(db, user, company_id, payload):
    contract = get_row(db, Contract, payload.get("contract_id"), company_id)
    direction = payload.get("direction")
    expect = "receipt" if contract.direction == "sale" else "payment"
    if direction != expect:
        raise BizError(MSG_DIRECTION)
    if contract.status != "已签订":
        raise BizError(MSG_NOT_SIGNED)
    party = _party(db, company_id, payload.get("party_id") or contract.party_id)
    if party.id != contract.party_id:
        raise BizError(MSG_DIRECTION)
    calc.lock_contracts(db, [contract.id])
    stages = calc.lock_stages(db, [contract.id])
    calc.refresh_settlement(db, contract)
    stage_map = {s.id: s for s in stages}
    lines = payload.get("lines") or []
    if not lines:
        raise BizError("请选择阶段")
    base_code = (payload.get("bill_code") or "").strip()
    if not base_code:
        base_code = next_daily_code(db, SettleBill, company_id, SettleBill.bill_code, "SK" if direction == "receipt" else "FK")
    account = payload.get("account_name") or None
    if account:
        found = q(db, FundAccount, company_id).filter(FundAccount.name == account, FundAccount.status == "启用").first()
        if not found:
            raise BizError("账户不存在或已停用")
    bills = []
    for index, line in enumerate(lines, start=1):
        stage = stage_map.get(int(line.get("stage_id")))
        if stage is None:
            raise BizError("阶段不存在")
        amount = round2(line.get("amount"))
        if amount <= 0:
            raise BizError("金额必须大于 0")
        remain = D(stage.plan_amount) - D(stage.settled_amount)
        if amount > remain:
            raise BizError(f"超出 {money_str(amount - remain)}")
        code = base_code if len(lines) == 1 else f"{base_code}-{index:02d}"
        ensure_code_free(db, SettleBill, company_id, SettleBill.bill_code, code)
        bill = SettleBill(
            bill_code=code,
            bill_date=parse_date(payload.get("bill_date")) or now().date(),
            direction=direction,
            party_id=party.id,
            party_name=party.name,
            contract_id=contract.id,
            stage_id=stage.id,
            amount=amount,
            account_name=account,
            remark=line.get("remark") or payload.get("remark") or "",
        )
        stamp_new(bill, user, company_id)
        db.add(bill)
        stage.settled_amount = round2(D(stage.settled_amount) + amount)
        bills.append(bill)
    db.flush()
    calc.refresh_settlement(db, contract)
    triggers = []
    for bill in bills:
        stage = stage_map[bill.stage_id]
        if D(stage.settled_amount) >= D(stage.plan_amount) and D(stage.plan_amount) > 0:
            if contract.direction == "purchase" and contract.arrival_stage_id == stage.id and not stage.arrival_triggered:
                triggers.append({"kind": "arrival", "stage_id": stage.id, "contract_id": contract.id, "message": "阶段付款已完成，物料是否制作到货单"})
            if contract.direction == "sale" and contract.ship_stage_id == stage.id and not stage.ship_triggered:
                triggers.append({"kind": "ship", "stage_id": stage.id, "contract_id": contract.id, "message": "阶段收款已完成，物料是否制作发货单"})
    op_log(db, user, company_id, "新增", "settle", bills[0].id, {"codes": [b.bill_code for b in bills]})
    return bills, triggers


def ack_trigger(db, user, company_id, stage_id, kind):
    stage = db.get(ContractStage, int(stage_id))
    if stage is None or stage.company_id != company_id or stage.deleted_at:
        raise BizError("阶段不存在")
    if kind == "arrival":
        stage.arrival_triggered = True
    elif kind == "ship":
        stage.ship_triggered = True
    else:
        raise BizError("类型不正确")
    bump(stage, user.employee_id)
    return stage


def update_settle(db, user, company_id, bill: SettleBill, payload):
    ensure_creator(bill, user)
    ensure_version(bill, payload.get("version"))
    contract = get_row(db, Contract, bill.contract_id, company_id)
    calc.lock_contracts(db, [contract.id])
    calc.lock_stages(db, [contract.id])
    stage = db.get(ContractStage, bill.stage_id)
    amount = round2(payload.get("amount"))
    if amount <= 0:
        raise BizError("金额必须大于 0")
    others = (
        db.query(SettleBill.amount)
        .filter(
            SettleBill.stage_id == stage.id,
            SettleBill.deleted_at.is_(None),
            SettleBill.id != bill.id,
        )
        .all()
    )
    used = sum((D(r[0]) for r in others), ZERO)
    if amount > D(stage.plan_amount) - used:
        raise BizError(f"超出 {money_str(amount - (D(stage.plan_amount) - used))}")
    account = payload.get("account_name") or None
    if account and account != bill.account_name:
        found = q(db, FundAccount, company_id).filter(FundAccount.name == account, FundAccount.status == "启用").first()
        if not found:
            raise BizError("账户不存在或已停用")
    bill.amount = amount
    bill.bill_date = parse_date(payload.get("bill_date")) or bill.bill_date
    bill.account_name = account
    bill.remark = payload.get("remark") or ""
    bump(bill, user.employee_id)
    calc.refresh_settlement(db, contract)
    op_log(db, user, company_id, "修改", "settle", bill.id, {"code": bill.bill_code, "amount": money_str(amount)})
    return bill


def delete_settle(db, user, company_id, bill: SettleBill):
    ensure_creator(bill, user)
    contract = get_row(db, Contract, bill.contract_id, company_id)
    calc.lock_contracts(db, [contract.id])
    calc.lock_stages(db, [contract.id])
    soft_delete(bill, user.employee_id)
    db.flush()
    calc.refresh_settlement(db, contract)
    op_log(db, user, company_id, "删除", "settle", bill.id, {"code": bill.bill_code})


def _invoice_lines(contract, raw_items, contract_items):
    rows = []
    seen = set()
    for raw in raw_items or []:
        code = (raw.get("material_code") or "").strip()
        if not code:
            raise BizError("物料编号不能为空")
        if code not in contract_items:
            raise BizError(f"物料 {code} 不在合同中")
        if code in seen:
            raise BizError(f"物料 {code} 重复")
        seen.add(code)
        qty = D(raw.get("qty"))
        if qty <= 0:
            raise BizError("数量必须大于 0")
        rate = D(raw.get("tax_rate") if raw.get("tax_rate") not in (None, "") else contract.tax_rate)
        manual = bool(raw.get("manual_tax"))
        if manual:
            part = back_calc_from_ex_tax(qty, raw.get("amount_ex_tax"), raw.get("tax"))
            price = part["price"]
            ex_tax = part["ex_tax"]
            tax = part["tax"]
            total = part["total"]
        else:
            price = D(raw.get("price"))
            if price < 0:
                raise BizError("含税单价不能小于 0")
            part = split_line(qty, price, rate)
            price = part["price"]
            ex_tax = part["ex_tax"]
            tax = part["tax"]
            total = part["total"]
        src = contract_items[code]
        rows.append(
            {
                "material_code": code,
                "name_cn": raw.get("name_cn") or src.name_cn,
                "name_en": raw.get("name_en") or src.name_en,
                "spec": raw.get("spec") or src.spec,
                "unit": raw.get("unit") or src.unit,
                "qty": qty,
                "price": price,
                "price_ex_tax": price_ex_tax_display(ex_tax, qty),
                "amount_ex_tax": ex_tax,
                "tax_rate": rate,
                "tax": tax,
                "total": total,
                "remark": raw.get("remark") or "",
                "manual_tax": manual,
            }
        )
    if not rows:
        raise BizError("至少一行明细才能保存")
    return rows


def save_invoice(db, user, company_id, payload, invoice: Invoice | None = None):
    contract = get_row(db, Contract, payload.get("contract_id"), company_id)
    direction = payload.get("direction") or (invoice.direction if invoice else None)
    expect = "output" if contract.direction == "sale" else "input"
    if direction != expect:
        raise BizError(MSG_DIRECTION)
    if invoice is None and contract.status != "已签订":
        raise BizError(MSG_NOT_SIGNED)
    if contract.invoice_locked and (invoice is None or invoice.contract_id == contract.id):
        raise BizError("已开票金额超出合同金额，禁止继续开票")
    party = _party(db, company_id, payload.get("party_id") or contract.party_id)
    if party.id != contract.party_id:
        raise BizError(MSG_DIRECTION)
    if party.status != "启用" and (invoice is None or invoice.party_id != party.id):
        raise BizError("客商已停用")
    invoice_no = (payload.get("invoice_no") or "").strip()
    if not invoice_no:
        raise BizError("发票号码不能为空")
    old_contract_id = invoice.contract_id if invoice else None
    calc.lock_contracts(db, [contract.id] + ([old_contract_id] if old_contract_id else []))
    contract_items = {row.material_code: row for row in calc.items_of(db, contract.id)}
    lines = _invoice_lines(contract, payload.get("items"), contract_items)
    if invoice:
        ensure_creator(invoice, user)
        ensure_version(invoice, payload.get("version"))
        if invoice_no != invoice.invoice_no:
            taken = db.query(Invoice).filter(Invoice.company_id == company_id, Invoice.invoice_no == invoice_no, Invoice.id != invoice.id).first()
            if taken:
                raise BizError("发票号码已存在")
    else:
        if db.query(Invoice).filter(Invoice.company_id == company_id, Invoice.invoice_no == invoice_no).first():
            raise BizError("发票号码已存在")
    total = round2(sum((row["total"] for row in lines), ZERO))
    for row in lines:
        already = calc.invoiced_qty(db, contract.id, row["material_code"])
        if invoice and invoice.contract_id == contract.id:
            old = (
                db.query(InvoiceItem)
                .filter(
                    InvoiceItem.invoice_id == invoice.id,
                    InvoiceItem.material_code == row["material_code"],
                    InvoiceItem.deleted_at.is_(None),
                )
                .first()
            )
            if old:
                already -= D(old.qty)
        limit = D(contract_items[row["material_code"]].qty)
        if already + row["qty"] > limit:
            raise BizError(f"物料 {row['material_code']} 超出 {format(already + row['qty'] - limit, 'f')}")
    already_amount = calc.invoiced_amount(db, contract.id)
    if invoice and invoice.contract_id == contract.id:
        already_amount -= D(invoice.total)
    if already_amount + total > D(contract.amount):
        raise BizError(f"超出 {money_str(already_amount + total - D(contract.amount))}")
    creating = invoice is None
    if creating:
        code = (payload.get("bill_code") or "").strip() or next_daily_code(
            db, Invoice, company_id, Invoice.bill_code, "XX" if direction == "output" else "JX"
        )
        ensure_code_free(db, Invoice, company_id, Invoice.bill_code, code)
        invoice = Invoice(direction=direction)
        stamp_new(invoice, user, company_id)
        db.add(invoice)
    else:
        code = (payload.get("bill_code") or invoice.bill_code).strip()
        if code != invoice.bill_code:
            ensure_code_free(db, Invoice, company_id, Invoice.bill_code, code, invoice.id)
    invoice.bill_code = code
    invoice.invoice_no = invoice_no
    invoice.invoice_date = parse_date(payload.get("invoice_date")) or now().date()
    invoice.invoice_type = payload.get("invoice_type") or "增值税专用发票"
    invoice.direction = direction
    invoice.party_id = party.id
    invoice.party_name = payload.get("party_name") or party.invoice_title or party.name
    invoice.party_tax_no = payload.get("party_tax_no") or party.tax_no
    invoice.contract_id = contract.id
    invoice.remark = payload.get("remark") or ""
    invoice.total = total
    rates = {row["tax_rate"] for row in lines}
    manual = any(row.get("manual_tax") for row in lines)
    if len(rates) == 1 and not manual:
        invoice.amount_ex_tax = line_ex_tax(total, next(iter(rates)))
        invoice.tax = line_tax(total, invoice.amount_ex_tax)
    else:
        invoice.amount_ex_tax = round2(sum((row["amount_ex_tax"] for row in lines), ZERO))
        invoice.tax = round2(sum((row["tax"] for row in lines), ZERO))
    db.flush()
    _sync_invoice_items(db, user, company_id, invoice, lines)
    if not creating:
        bump(invoice, user.employee_id)
    for cid in {contract.id, old_contract_id}:
        if not cid:
            continue
        other = get_row(db, Contract, cid, company_id)
        if calc.invoiced_amount(db, other.id) <= D(other.amount):
            other.invoice_locked = False
    op_log(db, user, company_id, "修改" if not creating else "新增", "invoice", invoice.id, {"no": invoice.invoice_no, "total": money_str(invoice.total)})
    return invoice


def _sync_invoice_items(db, user, company_id, invoice, lines):
    existing = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id, InvoiceItem.deleted_at.is_(None)).all()
    by_code = {row.material_code: row for row in existing}
    keep = set()
    for payload in lines:
        keep.add(payload["material_code"])
        row = by_code.get(payload["material_code"])
        if row is None:
            row = InvoiceItem(invoice_id=invoice.id)
            stamp_new(row, user, company_id)
            db.add(row)
        else:
            bump(row, user.employee_id)
        for key, value in payload.items():
            setattr(row, key, value)
    for code, row in by_code.items():
        if code not in keep:
            soft_delete(row, user.employee_id)


def delete_invoice(db, user, company_id, invoice: Invoice):
    ensure_creator(invoice, user)
    contract = get_row(db, Contract, invoice.contract_id, company_id)
    calc.lock_contracts(db, [contract.id])
    soft_delete(invoice, user.employee_id)
    for row in db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id, InvoiceItem.deleted_at.is_(None)).all():
        soft_delete(row, user.employee_id)
    db.flush()
    if calc.invoiced_amount(db, contract.id) <= D(contract.amount):
        contract.invoice_locked = False
    op_log(db, user, company_id, "删除", "invoice", invoice.id, {"no": invoice.invoice_no})


def sync_party_name(db, user, company_id, party: Party):
    """系统级动作：按 party_id 改名称快照，不受创建者限制，但递增 version。"""
    tables = [Contract, ContractOrder, SettleBill, Invoice]
    count = 0
    for model in tables:
        rows = (
            db.query(model)
            .filter(model.company_id == company_id, model.party_id == party.id, model.deleted_at.is_(None))
            .all()
        )
        for row in rows:
            if getattr(row, "party_name", None) != party.name:
                row.party_name = party.name
                bump(row, user.employee_id)
                count += 1
    op_log(db, user, company_id, "同步名称", "party", party.id, {"name": party.name, "count": count})
    return count
