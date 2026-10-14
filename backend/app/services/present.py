"""把模型转成接口字段。"""
from datetime import date, datetime
from decimal import Decimal

from ..money import D, ZERO, line_total, max0, money_str, qty_str, split_line
from ..models import Contract, ContractItem, ContractOrder, ContractStage, Party, Project, WmsBill, WmsItem
from . import calc
from .util import name_of, user_names


def _pct(part, whole) -> str:
    whole = D(whole)
    if whole <= 0:
        return "0%"
    return f"{int(D(part) / whole * 100)}%"


def dump(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dict):
        return {key: dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [dump(item) for item in value]
    return value


def audit(row, names):
    return {
        "id": row.id,
        "version": row.version,
        "created_by": row.created_by,
        "created_by_name": name_of(names, getattr(row, "created_by", "")),
        "created_at": dump(getattr(row, "created_at", None)),
        "updated_by": getattr(row, "updated_by", ""),
        "updated_by_name": name_of(names, getattr(row, "updated_by", "")),
        "updated_at": dump(getattr(row, "updated_at", None)),
    }


def contract_brief(db, rows):
    if not rows:
        return []
    ids = [row.id for row in rows]
    parties = {p.id: p for p in db.query(Party).filter(Party.id.in_([r.party_id for r in rows])).all()}
    project_ids = [r.project_id for r in rows if r.project_id]
    projects = {p.id: p for p in db.query(Project).filter(Project.id.in_(project_ids)).all()} if project_ids else {}
    parent_ids = [r.parent_contract_id for r in rows if r.parent_contract_id]
    parents = {p.id: p for p in db.query(Contract).filter(Contract.id.in_(parent_ids)).all()} if parent_ids else {}
    item_rows = db.query(ContractItem).filter(ContractItem.contract_id.in_(ids), ContractItem.deleted_at.is_(None)).all()
    stage_rows = db.query(ContractStage).filter(ContractStage.contract_id.in_(ids), ContractStage.deleted_at.is_(None)).all()
    names = user_names(db, [r.owner_id for r in rows] + [r.created_by for r in rows] + [r.updated_by for r in rows])
    items_by = {}
    for item in item_rows:
        items_by.setdefault(item.contract_id, []).append(item)
    stages_by = {}
    for stage in stage_rows:
        stages_by.setdefault(stage.contract_id, []).append(stage)
    orders = db.query(ContractOrder).filter(ContractOrder.contract_id.in_(ids), ContractOrder.deleted_at.is_(None)).all()
    order_by = {order.contract_id: order for order in orders}
    moved_map = _moved_qty_map(db, ids)
    result = []
    for row in rows:
        party = parties.get(row.party_id)
        project = projects.get(row.project_id)
        parent = parents.get(row.parent_contract_id)
        stages = sorted(stages_by.get(row.id, []), key=lambda s: (s.seq, s.id))
        items = items_by.get(row.id, [])
        done = sum(1 for stage in stages if D(stage.settled_amount) >= D(stage.plan_amount) and D(stage.plan_amount) > 0)
        pre_name = "预收款" if row.direction == "sale" else "预付款"
        prepaid = sum((D(stage.settled_amount) for stage in stages if pre_name in (stage.name or "")), ZERO)
        unpaid = max0(D(row.amount) - D(row.settled_sum))
        invoiced = calc.invoiced_amount(db, row.id)
        uninvoiced = max0(D(row.amount) - invoiced)
        sale = row.direction == "sale"
        raw_invoice = calc.invoice_label(db, row)
        if sale:
            invoice_state = {"无发票": "未开票", "部分": "部分开票", "已收到": "已开票"}.get(raw_invoice, raw_invoice)
        else:
            invoice_state = {"无发票": "未收票", "部分": "部分收票", "已收到": "已收票"}.get(raw_invoice, raw_invoice)
        result.append({
            **audit(row, names),
            "contract_code": row.contract_code,
            "name": row.name,
            "nature": row.nature,
            "parent_contract_id": row.parent_contract_id,
            "parent_code": parent.contract_code if parent else "",
            "direction": row.direction,
            "direction_label": "销售" if row.direction == "sale" else "采购",
            "type_name": row.type_name or "",
            "party_id": row.party_id,
            "party_code": party.code if party else "",
            "party_name": row.party_name or (party.name if party else ""),
            "project_id": row.project_id,
            "project_code": project.project_code if project else "",
            "project_name": project.name if project else "",
            "project_year": str(project.year) if project and project.year else "",
            "owner_id": row.owner_id,
            "owner_name": name_of(names, row.owner_id),
            "status": row.status,
            "archived_label": "未归档",
            "sign_date": dump(row.sign_date),
            "start_date": dump(row.start_date),
            "end_date": dump(row.end_date),
            "pricing": row.pricing,
            "pricing_label": "按实结算" if row.pricing == "actual" else "固定总价",
            "qty_total": qty_str(sum((D(item.qty) for item in items), ZERO)),
            "tax_rate": qty_str(row.tax_rate),
            "tax_text": f"{qty_str(row.tax_rate)}%",
            "amount_ex_tax": money_str(row.amount_ex_tax),
            "amount": money_str(row.amount),
            "due_total": money_str(row.amount),
            "paid_now": money_str(row.settled_sum),
            "unpaid_now": money_str(unpaid),
            "invoiced": money_str(invoiced),
            "uninvoiced": money_str(uninvoiced),
            "paid_not_invoiced": money_str(max0(D(row.settled_sum) - invoiced)),
            "invoiced_not_paid": money_str(max0(invoiced - D(row.settled_sum))),
            "pay_percent": _pct(row.settled_sum, row.amount),
            "invoice_percent": _pct(invoiced, row.amount),
            "move_state": calc.move_label(
                row.direction,
                ((item.qty, moved_map.get((row.id, "outbound" if sale else "inbound", item.material_code), ZERO)) for item in items),
            ),
            "invoice_state": invoice_state,
            "attachment": "无附件",
            "prepaid": money_str(prepaid),
            "stage_done": done,
            "stage_total": len(stages),
            "stage_text": f"{done}/{len(stages)}",
            "settled": money_str(row.settled_sum),
            "unpaid": money_str(unpaid),
            "pay_status": calc.pay_label(row.direction, row.settled_sum, row.amount),
            "invoice_status": calc.invoice_label(db, row),
            "remark": row.remark or "",
            "has_order": row.id in order_by,
            "order_id": order_by[row.id].id if row.id in order_by else None,
        })
    return result


def _moved_qty_map(db, contract_ids):
    rows = (
        db.query(WmsBill.contract_id, WmsBill.type, WmsItem.material_code, WmsItem.qty)
        .join(WmsItem, WmsItem.bill_id == WmsBill.id)
        .filter(
            WmsBill.contract_id.in_(contract_ids),
            WmsBill.deleted_at.is_(None),
            WmsItem.deleted_at.is_(None),
        )
        .all()
    )
    totals = {}
    for contract_id, bill_type, code, qty in rows:
        key = (contract_id, bill_type, code)
        totals[key] = totals.get(key, ZERO) + D(qty)
    return totals


def contract_detail(db, row: Contract):
    brief = contract_brief(db, [row])[0]
    items = []
    for item in calc.items_of(db, row.id):
        settled = calc.moved_qty(db, row, item.material_code)
        qty_for_money = settled if row.pricing == "actual" else D(item.qty)
        part = split_line(qty_for_money, item.price, row.tax_rate)
        items.append({
            "id": item.id,
            "material_code": item.material_code,
            "name_cn": item.name_cn or "",
            "name_en": item.name_en or "",
            "spec": item.spec or "",
            "unit": item.unit or "",
            "qty": qty_str(item.qty),
            "settled_qty": qty_str(settled),
            "price": money_str(item.price),
            "amount": money_str(part["total"]),
            "plan_no": item.plan_no or "",
            "plan_row": item.plan_row,
            "category": calc.equipment_name(item, calc.plan_of(db, row.company_id, item.material_code) if row.direction == "purchase" else None),
            "remark": item.remark or "",
            "invoiced_qty": qty_str(calc.invoiced_qty(db, row.id, item.material_code)),
            "uninvoiced_qty": qty_str(calc.uninvoiced_qty(db, row, item)),
        })
    stages = []
    for index, stage in enumerate(calc.stages_of(db, row.id)):
        remain = max0(D(stage.plan_amount) - D(stage.settled_amount))
        over = max0(D(stage.settled_amount) - D(stage.plan_amount))
        stages.append({
            "id": stage.id,
            "seq": stage.seq,
            "name": stage.name,
            "ratio": qty_str(stage.ratio or 0),
            "plan_amount": money_str(stage.plan_amount),
            "plan_date": dump(stage.plan_date),
            "settled_amount": money_str(stage.settled_amount),
            "remain": money_str(remain),
            "over": money_str(over),
            "remark": stage.remark or "",
            "arrival_triggered": bool(stage.arrival_triggered),
            "ship_triggered": bool(stage.ship_triggered),
            "is_arrival": row.arrival_stage_id == stage.id,
            "is_ship": row.ship_stage_id == stage.id,
            "index": index,
        })
    children = db.query(Contract).filter(Contract.parent_contract_id == row.id, Contract.deleted_at.is_(None)).all()
    brief.update({
        "content": row.content or "",
        "terms": row.terms or "",
        "remark": row.remark or "",
        "amount_manual": money_str(row.amount_manual or 0),
        "ship_address": row.ship_address or "",
        "contact_name": row.contact_name or "",
        "contact_phone": row.contact_phone or "",
        "party_tax_no": row.party_tax_no or "",
        "party_invoice_title": row.party_invoice_title or "",
        "party_invoice_phone": row.party_invoice_phone or "",
        "party_invoice_address": row.party_invoice_address or "",
        "party_address": row.party_address or "",
        "party_bank_name": row.party_bank_name or "",
        "party_account_name": row.party_account_name or "",
        "party_bank_account": row.party_bank_account or "",
        "party_bank_branch": row.party_bank_branch or "",
        "party_legal_name": row.party_legal_name or "",
        "party_agent": row.party_agent or "",
        "subject_name": row.subject_name or "",
        "transport_mode": row.transport_mode or "",
        "delivery_term": row.delivery_term or "",
        "freight_bearer": row.freight_bearer or "",
        "receiver_name": row.receiver_name or "",
        "acceptance_text": row.acceptance_text or "",
        "annex_note": row.annex_note or "",
        "items": items,
        "stages": stages,
        "supplements": [child.contract_code for child in children],
        "invoiced_amount": money_str(calc.invoiced_amount(db, row.id)),
        "ordered_amount": money_str(calc.ordered_amount(db, row.id)),
        "invoice_locked": bool(row.invoice_locked),
    })
    return brief


def order_lines(db, orders):
    if not orders:
        return []
    names = user_names(db, [o.owner_id for o in orders] + [o.created_by for o in orders])
    contracts = {c.id: c for c in db.query(Contract).filter(Contract.id.in_([o.contract_id for o in orders])).all()}
    fixed = []
    for order in orders:
        contract = contracts.get(order.contract_id)
        sale = order.direction == "sale"
        for item in calc.order_items(db, order.id):
            moved = calc.moved_qty(db, contract, item.material_code) if contract else ZERO
            fixed.append({
                **audit(order, names),
                "order_id": order.id,
                "order_code": order.order_code,
                "contract_id": order.contract_id,
                "contract_code": contract.contract_code if contract else "",
                "contract_name": contract.name if contract else "",
                "direction": order.direction,
                "party_id": order.party_id,
                "party_name": contract.party_name if contract else "",
                "owner_name": name_of(names, order.owner_id),
                "status": order.status,
                "status_label": "已关闭" if order.status == "closed" else "未关闭",
                "material_code": item.material_code,
                "name_cn": item.name_cn or "",
                "spec": item.spec or "",
                "unit": item.unit or "",
                "qty": qty_str(item.qty),
                "price": money_str(item.price),
                "amount": money_str(line_total(item.qty, item.price)),
                "order_amount": money_str(order.amount),
                "moved_text": calc.arrival_text(item.name_cn or "", item.unit or "", moved, item.qty, sale),
                "remark": order.remark or "",
            })
    return fixed


def order_detail(db, order):
    lines = order_lines(db, [order])
    contract = db.get(Contract, order.contract_id)
    names = user_names(db, [order.owner_id, order.created_by])
    return {
        **audit(order, names),
        "order_code": order.order_code,
        "contract_id": order.contract_id,
        "contract_code": contract.contract_code if contract else "",
        "contract_name": contract.name if contract else "",
        "direction": order.direction,
        "party_id": order.party_id,
        "party_name": contract.party_name if contract else "",
        "tax_rate": qty_str(order.tax_rate),
        "owner_id": order.owner_id,
        "owner_name": name_of(names, order.owner_id),
        "status": order.status,
        "status_label": "已关闭" if order.status == "closed" else "未关闭",
        "remark": order.remark or "",
        "amount": money_str(order.amount),
        "items": [
            {
                "material_code": line["material_code"],
                "name_cn": line["name_cn"],
                "spec": line["spec"],
                "unit": line["unit"],
                "qty": line["qty"],
                "price": line["price"],
                "amount": line["amount"],
                "moved_text": line["moved_text"],
            }
            for line in lines
        ],
    }
