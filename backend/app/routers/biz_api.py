from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse

from ..database import get_db
from ..deps import current_user
from ..errors import BizError
from ..models import (
    Company,
    Contract,
    ContractOrder,
    Invoice,
    InvoiceItem,
    Party,
    PartyContact,
    SettleBill,
    SysUser,
    WmsBill,
    WmsItem,
)
from ..response import ok, page
from ..services import calc, contract_docx, form_docx, importer, ops, refs
from ..services.present import contract_brief, contract_detail, dump, order_detail, order_lines
from ..services.util import (
    bump,
    ensure_creator,
    ensure_version,
    get_row,
    name_of,
    op_log,
    page_args,
    q,
    soft_delete,
    stamp_new,
    user_names,
)
from ..money import D, ZERO, money_str

router = APIRouter(prefix="/api")


def _pg(request: Request):
    return page_args(request.query_params.get("page"), request.query_params.get("pageSize"))


def _batch(db, user, company_id, model, items, deleter):
    rows = []
    for item in sorted(items, key=lambda row: int(row["id"])):
        row = get_row(db, model, item["id"], company_id)
        ensure_version(row, item.get("version"))
        rows.append(row)
    for row in rows:
        deleter(db, user, company_id, row)
    return len(rows)


@router.get("/parties")
def list_parties(request: Request, user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    query = q(db, Party, company_id)
    party_type = request.query_params.get("type")
    if party_type:
        query = query.filter(Party.type == party_type)
    cat_base = q(db, Party, company_id)
    if party_type:
        cat_base = cat_base.filter(Party.type == party_type)
    categories = sorted({
        text for (text,) in cat_base.with_entities(Party.supplier_category).distinct().all()
        if text and text not in ("供应商类别", "客户类别")
    })
    status = (request.query_params.get("status") or "").strip()
    if status:
        query = query.filter(Party.status == status)
    category = (request.query_params.get("category") or "").strip()
    if category:
        query = query.filter(Party.supplier_category == category)
    owner = (request.query_params.get("owner") or "").strip()
    if owner:
        person = db.query(SysUser).filter(SysUser.employee_id == owner, SysUser.deleted_at.is_(None)).first()
        if person and person.name and person.name != owner:
            query = query.filter((Party.salesman_id == owner) | (Party.salesman_id == person.name))
        else:
            query = query.filter(Party.salesman_id == owner)
    address = (request.query_params.get("address") or "").strip()
    if address:
        query = query.filter(Party.address.like(f"%{address}%"))
    keyword = (request.query_params.get("keyword") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (Party.code.like(like)) | (Party.name.like(like)) | (Party.short_name.like(like))
            | (Party.tax_no.like(like)) | (Party.bank_account.like(like)) | (Party.bank_name.like(like))
            | (Party.invoice_title.like(like))
        )
    rows = query.order_by(Party.id.desc()).all()
    page_no, size = _pg(request)
    names = user_names(db, [r.salesman_id for r in rows] + [r.created_by for r in rows])
    contacts = q(db, PartyContact, company_id).filter(PartyContact.is_default.is_(True)).all()
    contact_map = {row.party_id: row for row in contacts}
    items = []
    for row in rows:
        contact = contact_map.get(row.id)
        items.append({
            "id": row.id,
            "version": row.version,
            "code": row.code,
            "name": row.name,
            "short_name": row.short_name or "",
            "type": row.type,
            "tax_no": row.tax_no or "",
            "bank_account": row.bank_account or "",
            "bank_name": row.bank_name or "",
            "account_name": row.account_name or "",
            "bank_branch": row.bank_branch or "",
            "default_tax_rate": dump(row.default_tax_rate or 0),
            "status": row.status,
            "supplier_category": row.supplier_category or "",
            "salesman_id": row.salesman_id or "",
            "salesman_name": name_of(names, row.salesman_id),
            "invoice_title": row.invoice_title or "",
            "invoice_phone": row.invoice_phone or "",
            "invoice_address": row.invoice_address or "",
            "legal_name": row.legal_name or "",
            "agent_name": row.agent_name or "",
            "address": row.address or "",
            "email": row.email or "",
            "mobile": row.mobile or "",
            "remark": row.remark or "",
            "contact_name": contact.name if contact else "",
            "contact_phone": contact.phone if contact else "",
            "created_by": row.created_by,
            "created_by_name": name_of(names, row.created_by),
        })
    start = (page_no - 1) * size
    return page(items[start : start + size], len(items), page_no, size, categories=categories)


@router.get("/parties/{party_id}")
def get_party(party_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Party, party_id, user.session_company_id)
    contacts = q(db, PartyContact, user.session_company_id).filter(PartyContact.party_id == row.id).all()
    data = {
        "id": row.id,
        "version": row.version,
        "code": row.code,
        "name": row.name,
        "short_name": row.short_name or "",
        "type": row.type,
        "tax_no": row.tax_no or "",
        "bank_account": row.bank_account or "",
        "default_tax_rate": dump(row.default_tax_rate or 0),
        "status": row.status,
        "supplier_category": row.supplier_category or "",
        "salesman_id": row.salesman_id or "",
        "invoice_title": row.invoice_title or "",
        "address": row.address or "",
        "email": row.email or "",
        "mobile": row.mobile or "",
        "bank_name": row.bank_name or "",
        "account_name": row.account_name or "",
        "bank_branch": row.bank_branch or "",
        "invoice_phone": row.invoice_phone or "",
        "invoice_address": row.invoice_address or "",
        "legal_name": row.legal_name or "",
        "agent_name": row.agent_name or "",
        "remark": row.remark or "",
        "contacts": [{"id": c.id, "name": c.name, "phone": c.phone or "", "is_default": bool(c.is_default)} for c in contacts],
        "created_by": row.created_by,
    }
    return ok(data)


def _save_party(db, user, company_id, payload, row: Party | None):
    code = (payload.get("code") or "").strip()
    name = (payload.get("name") or "").strip()
    if not code or not name:
        raise BizError("编码和名称不能为空")
    party_type = payload.get("type") or (row.type if row else None)
    if party_type not in ("supplier", "customer"):
        raise BizError("类型不正确")
    if row:
        ensure_creator(row, user)
        ensure_version(row, payload.get("version"))
        if row.type != party_type:
            raise BizError("类型保存后不可改")
        if code != row.code:
            taken = db.query(Party).filter(Party.company_id == company_id, Party.code == code, Party.id != row.id).first()
            if taken:
                raise BizError("编号已存在")
    else:
        if db.query(Party).filter(Party.company_id == company_id, Party.code == code).first():
            raise BizError("编号已存在")
        row = Party(type=party_type)
        stamp_new(row, user, company_id)
        db.add(row)
    old_name = row.name if row.id else None
    row.code = code
    row.name = name
    row.short_name = payload.get("short_name") or ""
    row.type = party_type
    row.tax_no = payload.get("tax_no") or ""
    row.bank_account = payload.get("bank_account") or ""
    row.default_tax_rate = D(payload.get("default_tax_rate") or 0)
    row.status = payload.get("status") or "启用"
    row.supplier_category = payload.get("supplier_category") or ""
    row.salesman_id = payload.get("salesman_id") or ""
    row.invoice_title = payload.get("invoice_title") or ""
    row.address = payload.get("address") or ""
    row.email = payload.get("email") or ""
    row.mobile = payload.get("mobile") or ""
    row.bank_name = payload.get("bank_name") or ""
    row.account_name = payload.get("account_name") or ""
    row.bank_branch = payload.get("bank_branch") or ""
    row.invoice_phone = payload.get("invoice_phone") or ""
    row.invoice_address = payload.get("invoice_address") or ""
    if "legal_name" in payload or row.legal_name is None:
        row.legal_name = payload.get("legal_name") or ""
    if "agent_name" in payload or row.agent_name is None:
        row.agent_name = payload.get("agent_name") or ""
    row.remark = payload.get("remark") or ""
    if row.id:
        bump(row, user.employee_id)
    db.flush()
    existing = q(db, PartyContact, company_id).filter(PartyContact.party_id == row.id).all()
    for contact in existing:
        soft_delete(contact, user.employee_id)
    seen_default = False
    for raw in payload.get("contacts") or []:
        if not (raw.get("name") or "").strip():
            continue
        contact = PartyContact(party_id=row.id, name=raw.get("name").strip(), phone=raw.get("phone") or "", is_default=bool(raw.get("is_default")) and not seen_default)
        if contact.is_default:
            seen_default = True
        stamp_new(contact, user, company_id)
        db.add(contact)
    name_changed = old_name is not None and old_name != row.name
    op_log(db, user, company_id, "修改" if old_name is not None else "新增", "party", row.id, {"code": code, "name": name})
    return row, name_changed


@router.post("/parties")
def create_party(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row, _changed = _save_party(db, user, user.session_company_id, payload, None)
    return ok({"id": row.id, "version": row.version})


@router.put("/parties/{party_id}")
def update_party(party_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Party, party_id, user.session_company_id)
    row, changed = _save_party(db, user, user.session_company_id, payload, row)
    return ok({"id": row.id, "version": row.version, "need_name_sync": changed, "message": "是否同步更新引用此客商的单据？" if changed else ""})


@router.post("/parties/{party_id}/sync-name")
def sync_name(party_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Party, party_id, user.session_company_id)
    count = ops.sync_party_name(db, user, user.session_company_id, row)
    return ok({"count": count})


@router.post("/parties/sync-names")
def sync_names(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    count = 0
    for party_id in payload.get("ids") or []:
        row = get_row(db, Party, int(party_id), user.session_company_id)
        count += ops.sync_party_name(db, user, user.session_company_id, row)
    return ok({"count": count})


@router.delete("/parties/{party_id}")
def delete_party(party_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Party, party_id, user.session_company_id)
    ensure_version(row, version)
    ensure_creator(row, user)
    refs.refuse_party(db, user.session_company_id, row.id)
    soft_delete(row, user.employee_id)
    op_log(db, user, user.session_company_id, "删除", "party", row.id, {"code": row.code})
    return ok({"ok": True})


@router.post("/parties/batch-delete")
def batch_parties(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    def _one(db, user, company_id, row):
        ensure_creator(row, user)
        refs.refuse_party(db, company_id, row.id)
        soft_delete(row, user.employee_id)
    count = _batch(db, user, user.session_company_id, Party, payload.get("items") or [], _one)
    return ok({"count": count})


@router.get("/contracts")
def list_contracts(request: Request, user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    query = q(db, Contract, company_id)
    direction = request.query_params.get("direction")
    if direction:
        query = query.filter(Contract.direction == direction)
    if request.query_params.get("party_id"):
        query = query.filter(Contract.party_id == int(request.query_params.get("party_id")))
    if request.query_params.get("project_id"):
        query = query.filter(Contract.project_id == int(request.query_params.get("project_id")))
    if request.query_params.get("status"):
        query = query.filter(Contract.status == request.query_params.get("status"))
    if request.query_params.get("signed_only") == "1":
        query = query.filter(Contract.status == "已签订")
    if request.query_params.get("orderable") == "1":
        used = [r[0] for r in db.query(ContractOrder.contract_id).filter(ContractOrder.company_id == company_id, ContractOrder.deleted_at.is_(None)).all()]
        query = query.filter(Contract.status == "已签订")
        if used:
            query = query.filter(~Contract.id.in_(used))
    keyword = (request.query_params.get("keyword") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter((Contract.contract_code.like(like)) | (Contract.name.like(like)))
    rows = query.order_by(Contract.id.desc()).all()
    brief = contract_brief(db, rows)
    year = (request.query_params.get("year") or "").strip()
    pay_status = (request.query_params.get("pay_status") or "").strip()
    move_state = (request.query_params.get("move_state") or "").strip()
    invoice_state = (request.query_params.get("invoice_state") or "").strip()
    type_name = (request.query_params.get("type_name") or "").strip()
    sign_from = (request.query_params.get("sign_from") or "").strip()
    sign_to = (request.query_params.get("sign_to") or "").strip()
    if year:
        brief = [item for item in brief if (item.get("project_year") or "") == year]
    if pay_status:
        brief = [item for item in brief if item.get("pay_status") == pay_status]
    if move_state:
        brief = [item for item in brief if item.get("move_state") == move_state]
    if invoice_state:
        brief = [item for item in brief if item.get("invoice_state") == invoice_state]
    if type_name:
        brief = [item for item in brief if item.get("type_name") == type_name]
    if sign_from:
        brief = [item for item in brief if (item.get("sign_date") or "") >= sign_from]
    if sign_to:
        brief = [item for item in brief if (item.get("sign_date") or "") and item.get("sign_date") <= sign_to]
    start_from = (request.query_params.get("start_from") or "").strip()
    start_to = (request.query_params.get("start_to") or "").strip()
    end_from = (request.query_params.get("end_from") or "").strip()
    end_to = (request.query_params.get("end_to") or "").strip()
    if start_from:
        brief = [item for item in brief if (item.get("start_date") or "") >= start_from]
    if start_to:
        brief = [item for item in brief if (item.get("start_date") or "") and item.get("start_date") <= start_to]
    if end_from:
        brief = [item for item in brief if (item.get("end_date") or "") >= end_from]
    if end_to:
        brief = [item for item in brief if (item.get("end_date") or "") and item.get("end_date") <= end_to]
    if (request.query_params.get("archived") or "").strip() == "已归档":
        brief = []
    page_no, size = _pg(request)
    money_keys = ["amount_ex_tax", "amount", "settled", "unpaid", "prepaid", "due_total", "paid_now", "unpaid_now", "invoiced", "uninvoiced", "paid_not_invoiced", "invoiced_not_paid"]
    sums = {key: money_str(sum((D(item[key]) for item in brief), ZERO)) for key in money_keys}
    start = (page_no - 1) * size
    return page(brief[start : start + size], len(brief), page_no, size, sums=sums)


@router.get("/contracts/item-template")
def contract_item_template(direction: str = "purchase", user=Depends(current_user)):
    content, filename = importer.contract_item_template(direction)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)


@router.post("/contracts/parse-items")
async def parse_contract_items(
    file: UploadFile = File(...),
    direction: str = Form("purchase"),
    contract_id: str = Form(""),
    existing: str = Form(""),
    user=Depends(current_user),
    db=Depends(get_db),
):
    content = await file.read()
    codes = [code for code in existing.split(",") if code]
    current_id = int(contract_id) if str(contract_id).isdigit() else None
    items = importer.parse_contract_items(db, user.session_company_id, content, file.filename or "", direction, codes, current_id)
    return ok({"items": items, "matched": sum(1 for row in items if row.get("matched_plan"))})


@router.get("/contracts/{contract_id}")
def get_contract(contract_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Contract, contract_id, user.session_company_id)
    return ok(contract_detail(db, row))


@router.get("/contracts/{contract_id}/word")
def export_contract_word(contract_id: int, template_id: int | None = None, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Contract, contract_id, user.session_company_id)
    company = db.get(Company, user.session_company_id)
    content, filename = contract_docx.build_purchase_docx(db, row, company, template_id)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Download-Name": quote(filename),
    }
    from ..services.export_profile import media_type_for

    return StreamingResponse(BytesIO(content), media_type=media_type_for(filename), headers=headers)


@router.get("/forms/{doc_code}/{record_id}/word")
def export_form_word(doc_code: str, record_id: int, template_id: int | None = None, user=Depends(current_user), db=Depends(get_db)):
    company = db.get(Company, user.session_company_id)
    content, filename = form_docx.build_form(db, company, doc_code, record_id, template_id)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Download-Name": quote(filename),
    }
    from ..services.export_profile import media_type_for

    return StreamingResponse(BytesIO(content), media_type=media_type_for(filename), headers=headers)


@router.post("/contracts")
def create_contract(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = ops.save_contract(db, user, user.session_company_id, payload, None)
    return ok(contract_detail(db, row))


@router.put("/contracts/{contract_id}")
def update_contract(contract_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Contract, contract_id, user.session_company_id)
    row = ops.save_contract(db, user, user.session_company_id, payload, row)
    return ok(contract_detail(db, row))


@router.delete("/contracts/{contract_id}")
def remove_contract(contract_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Contract, contract_id, user.session_company_id)
    ensure_version(row, version)
    ops.delete_contract(db, user, user.session_company_id, row)
    return ok({"ok": True})


@router.post("/contracts/link-project")
def link_contract_project(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    count = ops.link_project(db, user, user.session_company_id, payload)
    return ok({"count": count})


@router.post("/contracts/batch-delete")
def batch_contracts(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    count = _batch(db, user, user.session_company_id, Contract, payload.get("items") or [], ops.delete_contract)
    return ok({"count": count})


@router.post("/contracts/{contract_id}/supplement")
def supplement(contract_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Contract, contract_id, user.session_company_id)
    return ok(ops.supplement_prefill(db, user.session_company_id, row))


@router.post("/purchase-contracts/generate-sale-contract")
def gen_sale(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    return ok(ops.merge_sale_prefill(db, user.session_company_id, payload.get("ids") or []))


@router.post("/contracts/{contract_id}/generate-arrival")
def gen_arrival(contract_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Contract, contract_id, user.session_company_id)
    return ok(ops.wms_prefill(db, user.session_company_id, row, "inbound"))


@router.post("/contracts/{contract_id}/generate-shipment")
def gen_ship(contract_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Contract, contract_id, user.session_company_id)
    return ok(ops.wms_prefill(db, user.session_company_id, row, "outbound"))


@router.post("/contracts/{contract_id}/generate-input-invoice")
def gen_input_invoice(contract_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Contract, contract_id, user.session_company_id)
    return ok(ops.input_invoice_prefill(db, user.session_company_id, row))


@router.post("/contracts/stages/{stage_id}/ack-trigger")
def ack(stage_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    ops.ack_trigger(db, user, user.session_company_id, stage_id, payload.get("kind"))
    return ok({"ok": True})


@router.get("/orders")
def list_orders(request: Request, user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    query = q(db, ContractOrder, company_id)
    if request.query_params.get("direction"):
        query = query.filter(ContractOrder.direction == request.query_params.get("direction"))
    if request.query_params.get("party_id"):
        query = query.filter(ContractOrder.party_id == int(request.query_params.get("party_id")))
    if request.query_params.get("contract_id"):
        query = query.filter(ContractOrder.contract_id == int(request.query_params.get("contract_id")))
    keyword = (request.query_params.get("keyword") or "").strip()
    rows = query.order_by(ContractOrder.id.desc()).all()
    if keyword:
        like = keyword.lower()
        kept = []
        for row in rows:
            contract = db.get(Contract, row.contract_id)
            text = " ".join([row.order_code, contract.contract_code if contract else "", contract.name if contract else ""]).lower()
            items = calc.order_items(db, row.id)
            mat = " ".join(f"{item.material_code} {item.name_cn or ''}" for item in items).lower()
            if like in text or like in mat:
                kept.append(row)
        rows = kept
    if request.query_params.get("material_code"):
        code = request.query_params.get("material_code")
        rows = [row for row in rows if any(item.material_code == code for item in calc.order_items(db, row.id))]
    lines = order_lines(db, rows)
    page_no, size = _pg(request)
    start = (page_no - 1) * size
    amount = sum((D(line["amount"]) for line in lines), ZERO)
    return page(lines[start : start + size], len(lines), page_no, size, sums={"amount": money_str(amount)})


@router.get("/orders/available-contracts")
def orderable(request: Request, user=Depends(current_user), db=Depends(get_db)):
    direction = request.query_params.get("direction")
    company_id = user.session_company_id
    used = {r[0] for r in db.query(ContractOrder.contract_id).filter(ContractOrder.company_id == company_id, ContractOrder.deleted_at.is_(None)).all()}
    query = q(db, Contract, company_id).filter(Contract.status == "已签订")
    if direction:
        query = query.filter(Contract.direction == direction)
    current = request.query_params.get("current_id")
    rows = []
    for row in query.order_by(Contract.id.desc()).all():
        if row.id in used and str(row.id) != str(current or ""):
            continue
        if not calc.items_of(db, row.id):
            continue
        rows.append(row)
    return ok(contract_brief(db, rows))


@router.get("/orders/{order_id}")
def get_order(order_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, ContractOrder, order_id, user.session_company_id)
    return ok(order_detail(db, row))


@router.post("/orders")
def create_order(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    direction = payload.get("direction")
    usable = q(db, Contract, company_id).filter(Contract.direction == direction, Contract.status == "已签订").all()
    used = {r[0] for r in db.query(ContractOrder.contract_id).filter(ContractOrder.company_id == company_id, ContractOrder.deleted_at.is_(None)).all()}
    if not any(row.id not in used for row in usable):
        raise BizError("请先去录入合同")
    row = ops.save_order(db, user, company_id, payload, None)
    return ok(order_detail(db, row))


@router.put("/orders/{order_id}")
def update_order(order_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, ContractOrder, order_id, user.session_company_id)
    row = ops.save_order(db, user, user.session_company_id, payload, row)
    return ok(order_detail(db, row))


@router.delete("/orders/{order_id}")
def remove_order(order_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, ContractOrder, order_id, user.session_company_id)
    ensure_version(row, version)
    ops.delete_order(db, user, user.session_company_id, row)
    return ok({"ok": True})


@router.post("/orders/batch-delete")
def batch_orders(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    count = _batch(db, user, user.session_company_id, ContractOrder, payload.get("items") or [], ops.delete_order)
    return ok({"count": count})


@router.post("/orders/{order_id}/close")
def close_order(order_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, ContractOrder, order_id, user.session_company_id)
    ops.close_order(db, user, user.session_company_id, row, payload.get("version"), reopen=False)
    return ok(order_detail(db, row))


@router.post("/orders/{order_id}/reopen")
def reopen_order(order_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, ContractOrder, order_id, user.session_company_id)
    ops.close_order(db, user, user.session_company_id, row, payload.get("version"), reopen=True)
    return ok(order_detail(db, row))


def _wms_list(db, company_id, bill_type, request):
    query = q(db, WmsBill, company_id).filter(WmsBill.type == bill_type)
    if request.query_params.get("party_id"):
        query = query.filter(WmsBill.party_id == int(request.query_params.get("party_id")))
    if request.query_params.get("warehouse_id"):
        query = query.filter(WmsBill.warehouse_id == int(request.query_params.get("warehouse_id")))
    if request.query_params.get("contract_id"):
        query = query.filter(WmsBill.contract_id == int(request.query_params.get("contract_id")))
    rows = query.order_by(WmsBill.id.desc()).all()
    names = user_names(db, [r.created_by for r in rows])
    items = []
    for row in rows:
        contract = db.get(Contract, row.contract_id)
        details = db.query(WmsItem).filter(WmsItem.bill_id == row.id, WmsItem.deleted_at.is_(None)).all()
        contract_items = {ci.material_code: ci for ci in calc.items_of(db, row.contract_id)} if row.contract_id else {}
        cats = []
        for item in details:
            src = contract_items.get(item.material_code)
            text = calc.equipment_name(item, src, calc.plan_of(db, company_id, item.material_code) if bill_type == "inbound" else None)
            if text and text not in cats:
                cats.append(text)
        items.append({
            "id": row.id,
            "version": row.version,
            "bill_code": row.bill_code,
            "bill_date": dump(row.bill_date),
            "type": row.type,
            "contract_id": row.contract_id,
            "contract_code": contract.contract_code if contract else "",
            "party_name": row.party_name or "",
            "category": "、".join(cats),
            "warehouse_id": row.warehouse_id,
            "qty": dump(sum((D(item.qty) for item in details), ZERO)),
            "amount": money_str(sum((D(item.amount) for item in details), ZERO)),
            "created_by_name": name_of(names, row.created_by),
            "remark": row.remark or "",
        })
    return items


@router.get("/wms-bills")
def list_wms(request: Request, user=Depends(current_user), db=Depends(get_db)):
    bill_type = request.query_params.get("type") or "inbound"
    items = _wms_list(db, user.session_company_id, bill_type, request)
    page_no, size = _pg(request)
    start = (page_no - 1) * size
    return page(items[start : start + size], len(items), page_no, size)


@router.get("/wms-bills/{bill_id}")
def get_wms(bill_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, WmsBill, bill_id, user.session_company_id)
    details = db.query(WmsItem).filter(WmsItem.bill_id == row.id, WmsItem.deleted_at.is_(None)).all()
    contract = db.get(Contract, row.contract_id)
    contract_items = {ci.material_code: ci for ci in calc.items_of(db, row.contract_id)} if row.contract_id else {}
    return ok({
        "id": row.id,
        "version": row.version,
        "bill_code": row.bill_code,
        "bill_date": dump(row.bill_date),
        "type": row.type,
        "contract_id": row.contract_id,
        "contract_code": contract.contract_code if contract else "",
        "party_id": row.party_id,
        "party_name": row.party_name or "",
        "warehouse_id": row.warehouse_id,
        "remark": row.remark or "",
        "created_by": row.created_by,
        "items": [{
            "material_code": item.material_code,
            "name_cn": item.name_cn or "",
            "spec": item.spec or "",
            "unit": item.unit or "",
            "qty": dump(item.qty),
            "price": money_str(item.price),
            "amount": money_str(item.amount),
            "category": calc.equipment_name(item, contract_items.get(item.material_code), calc.plan_of(db, user.session_company_id, item.material_code) if row.type == "inbound" else None),
        } for item in details],
    })


@router.post("/wms-bills")
def create_wms(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = ops.save_wms(db, user, user.session_company_id, payload, None)
    return ok({"id": row.id, "version": row.version, "bill_code": row.bill_code})


@router.put("/wms-bills/{bill_id}")
def update_wms(bill_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, WmsBill, bill_id, user.session_company_id)
    row = ops.save_wms(db, user, user.session_company_id, payload, row)
    return ok({"id": row.id, "version": row.version})


@router.delete("/wms-bills/{bill_id}")
def remove_wms(bill_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, WmsBill, bill_id, user.session_company_id)
    ensure_version(row, version)
    ops.delete_wms(db, user, user.session_company_id, row)
    return ok({"ok": True})


@router.post("/wms-bills/batch-delete")
def batch_wms(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    count = _batch(db, user, user.session_company_id, WmsBill, payload.get("items") or [], ops.delete_wms)
    return ok({"count": count})


@router.get("/settle-bills")
def list_settle(request: Request, user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    query = q(db, SettleBill, company_id)
    if request.query_params.get("direction"):
        query = query.filter(SettleBill.direction == request.query_params.get("direction"))
    if request.query_params.get("party_id"):
        query = query.filter(SettleBill.party_id == int(request.query_params.get("party_id")))
    if request.query_params.get("contract_id"):
        query = query.filter(SettleBill.contract_id == int(request.query_params.get("contract_id")))
    rows = query.order_by(SettleBill.id.desc()).all()
    items = []
    for row in rows:
        contract = db.get(Contract, row.contract_id)
        stage = db.get(__import__("backend.app.models", fromlist=["ContractStage"]).ContractStage, row.stage_id)
        items.append({
            "id": row.id,
            "version": row.version,
            "bill_code": row.bill_code,
            "bill_date": dump(row.bill_date),
            "direction": row.direction,
            "party_name": row.party_name or "",
            "party_id": row.party_id,
            "contract_id": row.contract_id,
            "contract_code": contract.contract_code if contract else "",
            "stage_id": row.stage_id,
            "stage_name": stage.name if stage else "",
            "amount": money_str(row.amount),
            "account_name": row.account_name or "",
            "remark": row.remark or "",
            "created_by": row.created_by,
        })
    page_no, size = _pg(request)
    start = (page_no - 1) * size
    total_amount = sum((D(item["amount"]) for item in items), ZERO)
    return page(items[start : start + size], len(items), page_no, size, sums={"amount": money_str(total_amount)})


@router.post("/settle-bills/multi-stage")
def create_settle(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    direction = payload.get("direction")
    contract_direction = "sale" if direction == "receipt" else "purchase"
    party_id = payload.get("party_id")
    contracts = q(db, Contract, company_id).filter(Contract.party_id == int(party_id), Contract.direction == contract_direction, Contract.status == "已签订").all() if party_id else []
    payable = []
    for contract in contracts:
        calc.refresh_settlement(db, contract)
        if any(D(stage.plan_amount) - D(stage.settled_amount) > 0 for stage in calc.stages_of(db, contract.id)):
            payable.append(contract)
    if party_id and not payable and not payload.get("lines"):
        raise BizError("请去维护合同与阶段")
    bills, triggers = ops.save_settle_many(db, user, company_id, payload)
    return ok({"ids": [bill.id for bill in bills], "triggers": triggers})


@router.put("/settle-bills/{bill_id}")
def update_settle(bill_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, SettleBill, bill_id, user.session_company_id)
    ops.update_settle(db, user, user.session_company_id, row, payload)
    return ok({"id": row.id, "version": row.version})


@router.delete("/settle-bills/{bill_id}")
def remove_settle(bill_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, SettleBill, bill_id, user.session_company_id)
    ensure_version(row, version)
    ops.delete_settle(db, user, user.session_company_id, row)
    return ok({"ok": True})


@router.post("/settle-bills/batch-delete")
def batch_settle(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    count = _batch(db, user, user.session_company_id, SettleBill, payload.get("items") or [], ops.delete_settle)
    return ok({"count": count})


@router.get("/invoices")
def list_invoices(request: Request, user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    query = q(db, Invoice, company_id)
    if request.query_params.get("direction"):
        query = query.filter(Invoice.direction == request.query_params.get("direction"))
    if request.query_params.get("party_id"):
        query = query.filter(Invoice.party_id == int(request.query_params.get("party_id")))
    if request.query_params.get("contract_id"):
        query = query.filter(Invoice.contract_id == int(request.query_params.get("contract_id")))
    if request.query_params.get("invoice_type"):
        query = query.filter(Invoice.invoice_type == request.query_params.get("invoice_type"))
    keyword = (request.query_params.get("keyword") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter((Invoice.bill_code.like(like)) | (Invoice.invoice_no.like(like)) | (Invoice.party_name.like(like)))
    rows = query.order_by(Invoice.id.desc()).all()
    names = user_names(db, [r.created_by for r in rows] + [r.updated_by for r in rows])
    items = []
    for row in rows:
        contract = db.get(Contract, row.contract_id)
        project = None
        if contract and contract.project_id:
            from ..models import Project
            project = db.get(Project, contract.project_id)
        party = db.get(Party, row.party_id)
        qty = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == row.id, InvoiceItem.deleted_at.is_(None)).all()
        stages = calc.stages_of(db, contract.id) if contract else []
        done = sum(1 for stage in stages if D(stage.settled_amount) >= D(stage.plan_amount) and D(stage.plan_amount) > 0)
        progress = "—" if not stages else f"{done}/{len(stages)}"
        open_stages = [stage for stage in stages if D(stage.plan_amount) - D(stage.settled_amount) > 0 and stage.plan_date]
        plan_date = min((stage.plan_date for stage in open_stages), default=None)
        items.append({
            "id": row.id,
            "version": row.version,
            "bill_date": dump(row.invoice_date),
            "bill_code": row.bill_code,
            "invoice_no": row.invoice_no,
            "invoice_type": row.invoice_type,
            "party_code": party.code if party else "",
            "party_name": row.party_name or "",
            "party_id": row.party_id,
            "amount_ex_tax": money_str(row.amount_ex_tax),
            "tax": money_str(row.tax),
            "total": money_str(row.total),
            "qty_total": dump(sum((D(item.qty) for item in qty), ZERO)),
            "contract_id": row.contract_id,
            "contract_code": contract.contract_code if contract else "",
            "contract_name": contract.name if contract else "",
            "project_code": project.project_code if project else "",
            "project_name": project.name if project else "",
            "project_id": contract.project_id if contract else None,
            "plan_pay_date": dump(plan_date),
            "settled": money_str(contract.settled_sum) if contract else "0.00",
            "unpaid": money_str(__import__("backend.app.money", fromlist=["max0"]).max0(D(contract.amount) - D(contract.settled_sum))) if contract else "0.00",
            "pay_status": calc.pay_label(contract.direction, contract.settled_sum, contract.amount) if contract else "",
            "pay_progress": progress,
            "party_tax_no": row.party_tax_no or "",
            "created_by_name": name_of(names, row.created_by),
            "created_at": dump(row.created_at),
            "updated_by_name": name_of(names, row.updated_by),
            "updated_at": dump(row.updated_at),
            "has_attachment": bool(row.attachments),
            "remark": row.remark or "",
            "created_by": row.created_by,
        })
    if request.query_params.get("project_id"):
        pid = int(request.query_params.get("project_id"))
        items = [item for item in items if item.get("project_id") == pid]
    if request.query_params.get("pay_status"):
        items = [item for item in items if item["pay_status"] == request.query_params.get("pay_status")]
    page_no, size = _pg(request)
    start = (page_no - 1) * size
    total_amount = sum((D(item["total"]) for item in items), ZERO)
    return page(items[start : start + size], len(items), page_no, size, sums={"total": money_str(total_amount)})


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Invoice, invoice_id, user.session_company_id)
    details = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == row.id, InvoiceItem.deleted_at.is_(None)).all()
    contract = db.get(Contract, row.contract_id)
    order = q(db, ContractOrder, user.session_company_id).filter(ContractOrder.contract_id == row.contract_id).first()
    return ok({
        "id": row.id,
        "version": row.version,
        "bill_code": row.bill_code,
        "invoice_no": row.invoice_no,
        "invoice_date": dump(row.invoice_date),
        "invoice_type": row.invoice_type,
        "direction": row.direction,
        "party_id": row.party_id,
        "party_name": row.party_name or "",
        "party_tax_no": row.party_tax_no or "",
        "contract_id": row.contract_id,
        "contract_code": contract.contract_code if contract else "",
        "order_code": order.order_code if order else "",
        "remark": row.remark or "",
        "total": money_str(row.total),
        "amount_ex_tax": money_str(row.amount_ex_tax),
        "tax": money_str(row.tax),
        "created_by": row.created_by,
        "items": [{
            "material_code": item.material_code,
            "name_cn": item.name_cn or "",
            "name_en": item.name_en or "",
            "spec": item.spec or "",
            "unit": item.unit or "",
            "qty": dump(item.qty),
            "price": dump(item.price),
            "price_ex_tax": dump(item.price_ex_tax or 0),
            "amount_ex_tax": money_str(item.amount_ex_tax),
            "tax_rate": dump(item.tax_rate),
            "tax": money_str(item.tax),
            "total": money_str(item.total),
            "remark": item.remark or "",
            "manual_tax": bool(item.manual_tax),
        } for item in details],
    })


@router.post("/invoices")
def create_invoice(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = ops.save_invoice(db, user, user.session_company_id, payload, None)
    return ok({"id": row.id, "version": row.version, "invoice_no": row.invoice_no})


@router.put("/invoices/{invoice_id}")
def update_invoice(invoice_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Invoice, invoice_id, user.session_company_id)
    row = ops.save_invoice(db, user, user.session_company_id, payload, row)
    return ok({"id": row.id, "version": row.version})


@router.delete("/invoices/{invoice_id}")
def remove_invoice(invoice_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Invoice, invoice_id, user.session_company_id)
    ensure_version(row, version)
    ops.delete_invoice(db, user, user.session_company_id, row)
    return ok({"ok": True})


@router.post("/invoices/batch-delete")
def batch_invoices(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    count = _batch(db, user, user.session_company_id, Invoice, payload.get("items") or [], ops.delete_invoice)
    return ok({"count": count})
