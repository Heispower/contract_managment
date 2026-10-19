"""项目、计划、基础资料、组织、统计、提醒、库存台账。"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP
from decimal import Decimal

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import or_, text

from ..config import ROOT
from ..database import get_db
from ..deps import current_user
from ..errors import BizError
from ..models import (
    CheckBill,
    Company,
    CompanyContact,
    Contract,
    ContractItem,
    ContractOrder,
    ContractStage,
    ContractType,
    ExportProfile,
    FundAccount,
    Goods,
    GoodsCategory,
    Invoice,
    LoginLog,
    OpLog,
    OtherBill,
    Party,
    Project,
    PurchasePlan,
    ReminderRecord,
    SettleBill,
    Stock,
    SysConfig,
    SysDept,
    SysPost,
    SysRole,
    SysUser,
    SysUserCompany,
    TransferBill,
    Warehouse,
    WmsBill,
    now,
)
from ..money import D, ZERO, max0, money_str, qty_str
from ..response import ok, page
from ..security import hash_password, make_token
from ..services import calc, refs
from ..services.export_profile import (
    build_field_workbook,
    ensure_export_profiles,
    list_profiles,
    remove_profile,
    save_profile,
    save_upload,
)
from ..services.present import dump
from ..services.util import (
    MSG_CODE,
    MSG_PERM,
    bump,
    ensure_code_free,
    ensure_creator,
    ensure_version,
    get_row,
    min_password,
    name_of,
    op_log,
    page_args,
    parse_date,
    q,
    soft_delete,
    stamp_new,
    user_names,
)

router = APIRouter(prefix="/api")


def _pg(request: Request):
    return page_args(request.query_params.get("page"), request.query_params.get("pageSize"))


def _slice(rows, request):
    page_no, size = _pg(request)
    start = (page_no - 1) * size
    return rows[start : start + size], len(rows), page_no, size


def _match_keyword(items, keyword, keys):
    text = (keyword or "").strip().lower()
    if not text:
        return items
    kept = []
    for item in items:
        blob = " ".join(str(item.get(key) or "") for key in keys).lower()
        if text in blob:
            kept.append(item)
    return kept


def _batch_version(db, model, company_id, items):
    rows = []
    for item in sorted(items, key=lambda row: int(row["id"])):
        row = get_row(db, model, item["id"], company_id)
        ensure_version(row, item.get("version"))
        rows.append(row)
    return rows


def _project_text(value):
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _project_choices(rows, attr):
    seen = []
    for row in rows:
        text = _project_text(getattr(row, attr))
        if text and text not in seen:
            seen.append(text)
    return seen


@router.get("/projects")
def list_projects(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = q(db, Project, user.session_company_id).order_by(Project.id.desc()).all()
    facets = {
        "types": sorted(_project_choices(rows, "project_type")),
        "sources": sorted(_project_choices(rows, "source")),
        "years": sorted(_project_choices(rows, "year"), reverse=True),
        "customers": sorted(_project_choices(rows, "customer_name")),
        "statuses": ["进行中", "已完成", "已终止"],
    }
    params = request.query_params
    project_type = (params.get("project_type") or "").strip()
    source = (params.get("source") or "").strip()
    year = (params.get("year") or "").strip()
    status = (params.get("status") or "").strip()
    customer = (params.get("customer_name") or "").strip()
    start = parse_date(params.get("start_date")) if (params.get("start_date") or "").strip() else None
    end = parse_date(params.get("end_date")) if (params.get("end_date") or "").strip() else None
    keyword = (params.get("keyword") or "").strip()
    picked = []
    for row in rows:
        if project_type and _project_text(row.project_type) != project_type:
            continue
        if source and _project_text(row.source) != source:
            continue
        if year and _project_text(row.year) != year:
            continue
        if status and (row.status or "") != status:
            continue
        if customer and _project_text(row.customer_name) != customer:
            continue
        if start and (row.start_date is None or row.start_date < start):
            continue
        if end and (row.end_date is None or row.end_date > end):
            continue
        if keyword:
            blob = " ".join([_project_text(row.project_code), _project_text(row.name), _project_text(row.customer_name)])
            if keyword.lower() not in blob.lower():
                continue
        picked.append(row)
    items = []
    for row in picked:
        codes = [c.contract_code for c in q(db, Contract, user.session_company_id).filter(Contract.project_id == row.id).all()]
        items.append({
            "id": row.id, "version": row.version, "project_code": row.project_code, "name": row.name,
            "year": row.year or "", "project_type": row.project_type or "", "source": row.source or "",
            "customer_name": row.customer_name or "", "start_date": row.start_date, "end_date": row.end_date,
            "status": row.status, "remark": row.remark or "", "contracts": "、".join(codes), "created_by": row.created_by,
        })
    chunk, total, page_no, size = _slice(items, request)
    return page(chunk, total, page_no, size, facets=facets)


def _save_project(db, user, company_id, payload, row):
    code = (payload.get("project_code") or "").strip()
    name = (payload.get("name") or "").strip()
    if not code or not name:
        raise BizError("项目编号和名称不能为空")
    if row:
        ensure_creator(row, user)
        ensure_version(row, payload.get("version"))
        if code != row.project_code:
            ensure_code_free(db, Project, company_id, Project.project_code, code, row.id)
    else:
        ensure_code_free(db, Project, company_id, Project.project_code, code)
        row = Project()
        stamp_new(row, user, company_id)
        db.add(row)
    row.project_code = code
    row.name = name
    row.year = payload.get("year") or ""
    row.project_type = (payload.get("project_type") or "").strip()
    row.source = (payload.get("source") or "").strip()
    row.customer_name = payload.get("customer_name") or ""
    row.start_date = parse_date(payload.get("start_date"))
    row.end_date = parse_date(payload.get("end_date"))
    row.status = payload.get("status") or "进行中"
    row.remark = payload.get("remark") or ""
    if row.id:
        bump(row, user.employee_id)
    op_log(db, user, company_id, "修改" if payload.get("version") else "新增", "project", row.project_code, {"name": name})
    db.flush()
    return row


@router.post("/projects")
def create_project(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = _save_project(db, user, user.session_company_id, payload, None)
    return ok({"id": row.id, "version": row.version})


@router.put("/projects/{row_id}")
def update_project(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Project, row_id, user.session_company_id)
    row = _save_project(db, user, user.session_company_id, payload, row)
    return ok({"id": row.id, "version": row.version})


def _delete_project(db, user, company_id, row):
    ensure_creator(row, user)
    refs.refuse_project(db, company_id, row.id)
    soft_delete(row, user.employee_id)


@router.delete("/projects/{row_id}")
def delete_project(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Project, row_id, user.session_company_id)
    ensure_version(row, version)
    _delete_project(db, user, user.session_company_id, row)
    return ok({"ok": True})


@router.post("/projects/batch-delete")
def batch_projects(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    for row in _batch_version(db, Project, user.session_company_id, payload.get("items") or []):
        _delete_project(db, user, user.session_company_id, row)
    return ok({"ok": True})


@router.get("/purchase-plans")
def list_plans(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = q(db, PurchasePlan, user.session_company_id).order_by(PurchasePlan.purchase_seq, PurchasePlan.id).all()
    items = []
    for row in rows:
        bought = calc.purchased_qty(db, user.session_company_id, row.material_code)
        remain = D(row.qty) - bought
        items.append({
            "id": row.id, "version": row.version, "plan_month": row.plan_month or "", "purchase_seq": row.purchase_seq or "",
            "material_code": row.material_code, "plan_no": row.plan_no or "", "category": row.category or "",
            "name_cn": row.name_cn or "", "name_en": row.name_en or "", "spec": row.spec or "", "unit": row.unit or "",
            "qty": qty_str(row.qty), "bought_qty": qty_str(bought), "remain_qty": qty_str(remain),
            "purchase_state": "采购完毕" if remain == 0 else "待采购",
            "purpose": row.purpose or "", "use_dept": row.use_dept or "", "stock_qty": qty_str(row.stock_qty) if row.stock_qty is not None else "",
            "transit_qty": qty_str(row.transit_qty) if row.transit_qty is not None else "",
            "consume_4m": qty_str(row.consume_4m) if row.consume_4m is not None else "",
            "remark": row.remark or "", "created_by": row.created_by,
        })
    keyword = (request.query_params.get("keyword") or "").strip()
    plan_month = (request.query_params.get("plan_month") or "").strip()
    name_cn = (request.query_params.get("name_cn") or "").strip()
    purchase_state = (request.query_params.get("purchase_state") or "").strip()
    if keyword:
        items = [item for item in items if keyword in " ".join(str(item.get(key, "")) for key in ("material_code", "name_cn", "plan_no", "spec", "category"))]
    if plan_month:
        items = [item for item in items if plan_month in item["plan_month"]]
    if name_cn:
        items = [item for item in items if name_cn in item["name_cn"]]
    if purchase_state in ("待采购", "采购完毕"):
        items = [item for item in items if item["purchase_state"] == purchase_state]
    chunk, total, page_no, size = _slice(items, request)
    return page(chunk, total, page_no, size)


@router.get("/purchase-plans/available")
def available_plans(request: Request, user=Depends(current_user), db=Depends(get_db)):
    chosen = set((request.query_params.get("chosen") or "").split(",")) - {""}
    items = []
    for row in q(db, PurchasePlan, user.session_company_id).all():
        if row.material_code in chosen:
            continue
        bought = calc.purchased_qty(db, user.session_company_id, row.material_code)
        remain = D(row.qty) - bought
        if remain <= 0:
            continue
        items.append({
            "id": row.id, "material_code": row.material_code, "name_cn": row.name_cn or "", "name_en": row.name_en or "",
            "spec": row.spec or "", "unit": row.unit or "", "plan_no": row.plan_no or "",
            "category": row.category or "",
            "plan_row": int(row.purchase_seq) if str(row.purchase_seq or "").isdigit() else None,
            "remain_qty": qty_str(remain),
        })
    return ok(items)


@router.put("/purchase-plans/{row_id}")
def update_plan(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, PurchasePlan, row_id, user.session_company_id)
    ensure_creator(row, user)
    ensure_version(row, payload.get("version"))
    code = (payload.get("material_code") or row.material_code or "").strip()
    if code != row.material_code:
        raise BizError("物料编号不支持修改")
    qty = D(payload.get("qty") if payload.get("qty") not in (None, "") else row.qty)
    if qty <= 0:
        raise BizError("采购数量必须大于 0")
    bought = calc.purchased_qty(db, user.session_company_id, row.material_code)
    if qty < bought:
        raise BizError(f"采购数量不能小于已采购数量 {qty_str(bought)}")
    for key in ("plan_month", "purchase_seq", "plan_no", "category", "name_cn", "name_en", "spec", "unit", "purpose", "use_dept", "remark"):
        if key in payload:
            setattr(row, key, payload.get(key) or "")
    for key in ("stock_qty", "transit_qty", "consume_4m"):
        if key in payload:
            raw = payload.get(key)
            setattr(row, key, None if raw in (None, "") else D(raw))
    row.qty = qty
    bump(row, user.employee_id)
    op_log(db, user, user.session_company_id, "修改", "purchase_plan", row.id, {"code": row.material_code, "qty": qty_str(qty)})
    return ok({"id": row.id, "version": row.version})


@router.delete("/purchase-plans/{row_id}")
def delete_plan(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, PurchasePlan, row_id, user.session_company_id)
    ensure_version(row, version)
    ensure_creator(row, user)
    refs.refuse_plan(db, user.session_company_id, row.material_code)
    soft_delete(row, user.employee_id)
    return ok({"ok": True})


@router.post("/purchase-plans/batch-delete")
def batch_plans(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    for row in _batch_version(db, PurchasePlan, user.session_company_id, payload.get("items") or []):
        ensure_creator(row, user)
        refs.refuse_plan(db, user.session_company_id, row.material_code)
        soft_delete(row, user.employee_id)
    return ok({"ok": True})


def _simple_list(db, model, company_id):
    return q(db, model, company_id).order_by(model.id.desc()).all()


@router.get("/fund-accounts")
def list_accounts(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = _simple_list(db, FundAccount, user.session_company_id)
    if request.query_params.get("status"):
        rows = [row for row in rows if row.status == request.query_params.get("status")]
    items = [{"id": r.id, "version": r.version, "code": r.code, "name": r.name, "account_no": r.account_no or "", "status": r.status, "created_by": r.created_by} for r in rows]
    items = _match_keyword(items, request.query_params.get("keyword"), ("code", "name", "account_no", "status"))
    chunk, total, page_no, size = _slice(items, request)
    return page(chunk, total, page_no, size)


def _save_account(db, user, company_id, payload, row):
    code = (payload.get("code") or "").strip()
    name = (payload.get("name") or "").strip()
    if not code or not name:
        raise BizError("编码和名称不能为空")
    if row is None:
        ensure_code_free(db, FundAccount, company_id, FundAccount.code, code)
        row = FundAccount()
        stamp_new(row, user, company_id)
        db.add(row)
    else:
        ensure_version(row, payload.get("version"))
        if code != row.code:
            ensure_code_free(db, FundAccount, company_id, FundAccount.code, code, row.id)
        bump(row, user.employee_id)
    row.code = code
    row.name = name
    row.account_no = payload.get("account_no") or ""
    row.status = payload.get("status") or "启用"
    db.flush()
    return row


@router.post("/fund-accounts")
def create_account(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = _save_account(db, user, user.session_company_id, payload, None)
    return ok({"id": row.id, "version": row.version})


@router.put("/fund-accounts/{row_id}")
def update_account(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, FundAccount, row_id, user.session_company_id)
    row = _save_account(db, user, user.session_company_id, payload, row)
    return ok({"id": row.id, "version": row.version})


@router.delete("/fund-accounts/{row_id}")
def delete_account(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, FundAccount, row_id, user.session_company_id)
    ensure_version(row, version)
    refs.refuse_account(db, user.session_company_id, row.name)
    soft_delete(row, user.employee_id)
    return ok({"ok": True})


@router.post("/fund-accounts/batch-delete")
def batch_accounts(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    rows = _batch_version(db, FundAccount, company_id, payload.get("items") or [])
    for row in rows:
        refs.refuse_account(db, company_id, row.name)
        soft_delete(row, user.employee_id)
    return ok({"count": len(rows)})


@router.get("/contract-types")
def list_types(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = _simple_list(db, ContractType, user.session_company_id)
    if request.query_params.get("status"):
        rows = [row for row in rows if row.status == request.query_params.get("status")]
    items = [{"id": r.id, "version": r.version, "code": r.code, "name": r.name, "remark": r.remark or "", "status": r.status} for r in rows]
    items = _match_keyword(items, request.query_params.get("keyword"), ("code", "name", "remark", "status"))
    chunk, total, page_no, size = _slice(items, request)
    return page(chunk, total, page_no, size)


@router.post("/contract-types")
def create_type(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    code = (payload.get("code") or "").strip()
    ensure_code_free(db, ContractType, user.session_company_id, ContractType.code, code)
    row = ContractType(code=code, name=payload.get("name") or "", remark=payload.get("remark") or "", status=payload.get("status") or "启用")
    stamp_new(row, user, user.session_company_id)
    db.add(row)
    db.flush()
    return ok({"id": row.id, "version": row.version})


@router.put("/contract-types/{row_id}")
def update_type(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, ContractType, row_id, user.session_company_id)
    ensure_version(row, payload.get("version"))
    row.name = payload.get("name") or row.name
    row.remark = payload.get("remark") or ""
    row.status = payload.get("status") or row.status
    bump(row, user.employee_id)
    return ok({"id": row.id, "version": row.version})


@router.delete("/contract-types/{row_id}")
def delete_type(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, ContractType, row_id, user.session_company_id)
    ensure_version(row, version)
    soft_delete(row, user.employee_id)
    return ok({"ok": True})


@router.post("/contract-types/batch-delete")
def batch_types(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    rows = _batch_version(db, ContractType, user.session_company_id, payload.get("items") or [])
    for row in rows:
        soft_delete(row, user.employee_id)
    return ok({"count": len(rows)})


@router.get("/warehouses")
def list_warehouses(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = _simple_list(db, Warehouse, user.session_company_id)
    if request.query_params.get("status"):
        rows = [row for row in rows if row.status == request.query_params.get("status")]
    items = [{"id": r.id, "version": r.version, "code": r.code, "name": r.name, "remark": r.remark or "", "status": r.status} for r in rows]
    items = _match_keyword(items, request.query_params.get("keyword"), ("code", "name", "remark", "status"))
    chunk, total, page_no, size = _slice(items, request)
    return page(chunk, total, page_no, size)


@router.post("/warehouses")
def create_warehouse(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    code = (payload.get("code") or "").strip()
    ensure_code_free(db, Warehouse, user.session_company_id, Warehouse.code, code)
    row = Warehouse(code=code, name=payload.get("name") or "", remark=payload.get("remark") or "", status=payload.get("status") or "启用")
    stamp_new(row, user, user.session_company_id)
    db.add(row)
    db.flush()
    return ok({"id": row.id, "version": row.version})


@router.put("/warehouses/{row_id}")
def update_warehouse(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Warehouse, row_id, user.session_company_id)
    ensure_version(row, payload.get("version"))
    if payload.get("status") == "停用" and row.status != "停用":
        stocks = db.query(Stock).filter(Stock.company_id == user.session_company_id, Stock.warehouse_id == row.id, Stock.deleted_at.is_(None)).all()
        if any(D(item.qty) != 0 for item in stocks):
            raise BizError("库存余额不为零，不能停用")
        for model, field in ((WmsBill, WmsBill.warehouse_id), (TransferBill, None), (CheckBill, CheckBill.warehouse_id)):
            if model is TransferBill:
                hit = q(db, TransferBill, user.session_company_id).filter(or_(TransferBill.warehouse_out == row.id, TransferBill.warehouse_in == row.id)).first()
            else:
                hit = q(db, model, user.session_company_id).filter(field == row.id).first()
            if hit:
                raise BizError("存在未删除的仓储单据，不能停用")
    row.name = payload.get("name") or row.name
    row.remark = payload.get("remark") or ""
    row.status = payload.get("status") or row.status
    bump(row, user.employee_id)
    return ok({"id": row.id, "version": row.version})


@router.delete("/warehouses/{row_id}")
def delete_warehouse(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Warehouse, row_id, user.session_company_id)
    ensure_version(row, version)
    refs.refuse_warehouse(db, user.session_company_id, row.id)
    soft_delete(row, user.employee_id)
    return ok({"ok": True})


@router.post("/warehouses/batch-delete")
def batch_warehouses(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    rows = _batch_version(db, Warehouse, company_id, payload.get("items") or [])
    for row in rows:
        refs.refuse_warehouse(db, company_id, row.id)
        soft_delete(row, user.employee_id)
    return ok({"count": len(rows)})


@router.get("/goods")
def list_goods(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = _simple_list(db, Goods, user.session_company_id)
    keyword = (request.query_params.get("keyword") or "").strip()
    items = [{"id": r.id, "version": r.version, "material_code": r.material_code, "name": r.name, "spec": r.spec or "", "unit": r.unit, "category_code": r.category_code or "", "price": money_str(r.price or 0), "created_by": r.created_by} for r in rows]
    items = _match_keyword(items, keyword, ("material_code", "name", "spec", "unit", "category_code"))
    chunk, total, page_no, size = _slice(items, request)
    return page(chunk, total, page_no, size)


@router.post("/goods")
def create_goods(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    code = (payload.get("material_code") or "").strip()
    ensure_code_free(db, Goods, user.session_company_id, Goods.material_code, code)
    row = Goods(material_code=code, name=payload.get("name") or "", spec=payload.get("spec") or "", unit=payload.get("unit") or "", category_code=payload.get("category_code") or "", price=D(payload.get("price") or 0))
    stamp_new(row, user, user.session_company_id)
    db.add(row)
    db.flush()
    return ok({"id": row.id, "version": row.version})


@router.put("/goods/{row_id}")
def update_goods(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Goods, row_id, user.session_company_id)
    ensure_version(row, payload.get("version"))
    ensure_creator(row, user)
    row.name = payload.get("name") or row.name
    row.spec = payload.get("spec") or ""
    row.unit = payload.get("unit") or row.unit
    row.category_code = payload.get("category_code") or ""
    row.price = D(payload.get("price") or 0)
    bump(row, user.employee_id)
    return ok({"id": row.id, "version": row.version})


@router.delete("/goods/{row_id}")
def delete_goods(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Goods, row_id, user.session_company_id)
    ensure_version(row, version)
    refs.refuse_goods(db, user.session_company_id, row.material_code)
    soft_delete(row, user.employee_id)
    return ok({"ok": True})


@router.post("/goods/batch-delete")
def batch_goods(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    rows = _batch_version(db, Goods, company_id, payload.get("items") or [])
    for row in rows:
        refs.refuse_goods(db, company_id, row.material_code)
        soft_delete(row, user.employee_id)
    return ok({"count": len(rows)})


@router.get("/goods-categories")
def list_cats(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = _simple_list(db, GoodsCategory, user.session_company_id)
    items = [{"id": r.id, "version": r.version, "code": r.code, "name": r.name, "remark": r.remark or ""} for r in rows]
    items = _match_keyword(items, request.query_params.get("keyword"), ("code", "name", "remark"))
    chunk, total, page_no, size = _slice(items, request)
    return page(chunk, total, page_no, size)


@router.post("/goods-categories")
def create_cat(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    code = (payload.get("code") or "").strip()
    ensure_code_free(db, GoodsCategory, user.session_company_id, GoodsCategory.code, code)
    row = GoodsCategory(code=code, name=payload.get("name") or "", remark=payload.get("remark") or "")
    stamp_new(row, user, user.session_company_id)
    db.add(row)
    db.flush()
    return ok({"id": row.id, "version": row.version})


@router.put("/goods-categories/{row_id}")
def update_cat(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, GoodsCategory, row_id, user.session_company_id)
    ensure_version(row, payload.get("version"))
    row.name = payload.get("name") or row.name
    row.remark = payload.get("remark") or ""
    bump(row, user.employee_id)
    return ok({"id": row.id, "version": row.version})


@router.delete("/goods-categories/{row_id}")
def delete_cat(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, GoodsCategory, row_id, user.session_company_id)
    ensure_version(row, version)
    refs.refuse_category(db, user.session_company_id, row.code)
    soft_delete(row, user.employee_id)
    return ok({"ok": True})


@router.post("/goods-categories/batch-delete")
def batch_cats(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    rows = _batch_version(db, GoodsCategory, company_id, payload.get("items") or [])
    for row in rows:
        refs.refuse_category(db, company_id, row.code)
        soft_delete(row, user.employee_id)
    return ok({"count": len(rows)})


_COMPANY_BUSY = (
    "party", "project", "purchase_plan", "goods", "contract", "contract_order",
    "invoice", "settle_bill", "other_bill", "wms_bill", "stock", "transfer_bill", "check_bill",
)


def _company_text(value):
    return (value or "").strip()


def _company_contacts(db, company_id):
    rows = (
        db.query(CompanyContact)
        .filter(CompanyContact.company_id == company_id, CompanyContact.deleted_at.is_(None))
        .order_by(CompanyContact.id)
        .all()
    )
    return [{"id": row.id, "name": row.name, "phone": row.phone or "", "is_default": bool(row.is_default)} for row in rows]


def _company_view(db, row: Company):
    return {
        "id": row.id,
        "version": row.version,
        "code": row.code or "",
        "name": row.name or "",
        "short_name": row.short_name or "",
        "status": row.status or "启用",
        "default_tax_rate": qty_str(row.default_tax_rate if row.default_tax_rate is not None else 13),
        "salesman_id": row.salesman_id or "",
        "tax_no": row.tax_no or "",
        "invoice_title": row.invoice_title or "",
        "address": row.address or "",
        "email": row.email or "",
        "mobile": row.mobile or "",
        "bank_name": row.bank_name or "",
        "account_name": row.account_name or "",
        "bank_account": row.bank_account or "",
        "bank_branch": row.bank_branch or "",
        "invoice_phone": row.invoice_phone or "",
        "invoice_address": row.invoice_address or "",
        "legal_name": row.legal_name or "",
        "agent_name": row.agent_name or "",
        "remark": row.remark or "",
        "contacts": _company_contacts(db, row.id),
    }


def _fill_company(row: Company, payload: dict):
    name = _company_text(payload.get("name"))
    short_name = _company_text(payload.get("short_name")) or name
    if not name:
        raise BizError("公司名称不能为空")
    row.code = _company_text(payload.get("code"))
    row.name = name
    row.short_name = short_name
    row.status = payload.get("status") or "启用"
    row.default_tax_rate = D(payload.get("default_tax_rate") or 0)
    row.salesman_id = _company_text(payload.get("salesman_id"))
    row.tax_no = _company_text(payload.get("tax_no"))
    row.invoice_title = _company_text(payload.get("invoice_title"))
    row.address = _company_text(payload.get("address"))
    row.email = _company_text(payload.get("email"))
    row.mobile = _company_text(payload.get("mobile"))
    row.bank_name = _company_text(payload.get("bank_name"))
    row.account_name = _company_text(payload.get("account_name"))
    row.bank_account = _company_text(payload.get("bank_account"))
    row.bank_branch = _company_text(payload.get("bank_branch"))
    row.invoice_phone = _company_text(payload.get("invoice_phone"))
    row.invoice_address = _company_text(payload.get("invoice_address"))
    row.legal_name = _company_text(payload.get("legal_name"))
    row.agent_name = _company_text(payload.get("agent_name"))
    row.remark = _company_text(payload.get("remark"))


def _save_company_contacts(db, user, row: Company, payload: dict):
    existing = db.query(CompanyContact).filter(CompanyContact.company_id == row.id, CompanyContact.deleted_at.is_(None)).all()
    for contact in existing:
        soft_delete(contact, user.employee_id)
    seen_default = False
    for raw in payload.get("contacts") or []:
        name = _company_text(raw.get("name"))
        if not name:
            continue
        contact = CompanyContact(
            company_id=row.id,
            name=name,
            phone=_company_text(raw.get("phone")),
            is_default=bool(raw.get("is_default")) and not seen_default,
        )
        if contact.is_default:
            seen_default = True
        contact.version = 1
        contact.created_by = user.employee_id
        contact.updated_by = user.employee_id
        contact.created_at = now()
        contact.updated_at = now()
        db.add(contact)


def _company_has_data(db, company_id: int) -> bool:
    for table in _COMPANY_BUSY:
        count = db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE company_id = :company_id"), {"company_id": company_id}).scalar()
        if count:
            return True
    return False


@router.get("/companies")
def list_companies(user=Depends(current_user), db=Depends(get_db)):
    rows = db.query(Company).filter(Company.deleted_at.is_(None)).order_by(Company.id).all()
    if not user.is_super_admin:
        ids = {r.company_id for r in db.query(SysUserCompany).filter(SysUserCompany.employee_id == user.employee_id).all()}
        rows = [row for row in rows if row.id in ids]
    return ok([_company_view(db, row) for row in rows])


@router.post("/companies")
def create_company(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    code = _company_text(payload.get("code"))
    if code and db.query(Company).filter(Company.code == code, Company.deleted_at.is_(None)).first():
        raise BizError("编号已存在")
    row = Company(name="", short_name="")
    _fill_company(row, payload)
    row.version = 1
    row.created_by = user.employee_id
    row.updated_by = user.employee_id
    row.created_at = now()
    row.updated_at = now()
    db.add(row)
    db.flush()
    _save_company_contacts(db, user, row, payload)
    wh = Warehouse(company_id=row.id, code="MAIN", name="主仓", status="启用")
    stamp_new(wh, user, row.id)
    db.add(wh)
    ensure_export_profiles(db)
    op_log(db, user, row.id, "新增", "company", row.id, {"name": row.short_name})
    return ok({"id": row.id, "version": row.version})


@router.put("/companies/{row_id}")
def update_company(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = db.get(Company, row_id)
    if row is None or row.deleted_at:
        raise BizError("数据不存在")
    ensure_version(row, payload.get("version"))
    code = _company_text(payload.get("code"))
    if code and code != (row.code or ""):
        taken = db.query(Company).filter(Company.code == code, Company.id != row.id, Company.deleted_at.is_(None)).first()
        if taken:
            raise BizError("编号已存在")
    _fill_company(row, payload)
    _save_company_contacts(db, user, row, payload)
    bump(row, user.employee_id)
    return ok({"id": row.id, "version": row.version, "short_name": row.short_name})


@router.delete("/companies/{row_id}")
def delete_company(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = db.get(Company, row_id)
    if row is None or row.deleted_at:
        raise BizError("数据不存在")
    ensure_version(row, version)
    others = db.query(Company).filter(Company.deleted_at.is_(None), Company.id != row.id).order_by(Company.id).all()
    if not others:
        raise BizError("至少保留一个公司")
    if _company_has_data(db, row.id):
        raise BizError("该公司下还有业务资料，不能删除")
    for model in (Warehouse, FundAccount, ContractType, GoodsCategory, SysRole, SysDept, SysPost, ExportProfile):
        for item in db.query(model).filter(model.company_id == row.id, model.deleted_at.is_(None)).all():
            soft_delete(item, user.employee_id)
    for contact in db.query(CompanyContact).filter(CompanyContact.company_id == row.id, CompanyContact.deleted_at.is_(None)).all():
        soft_delete(contact, user.employee_id)
    db.query(SysUserCompany).filter(SysUserCompany.company_id == row.id).delete()
    soft_delete(row, user.employee_id)
    op_log(db, user, row.id, "删除", "company", row.id, {"name": row.short_name})
    token = None
    switch_id = None
    if user.session_company_id == row.id:
        target = next((item for item in others if "博赛" in (item.short_name or "") or "博赛" in (item.name or "")), others[0])
        switch_id = target.id
        token = make_token(user, switch_id)
    return ok({"ok": True, "token": token, "company_id": switch_id})


@router.get("/export-profiles/fields")
def download_export_fields(user=Depends(current_user)):
    content = build_field_workbook()
    folder = ROOT / "需求的模板"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "表单字段.xlsx").write_bytes(content)
    filename = quote("表单字段.xlsx")
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/export-profiles")
def get_export_profiles(request: Request, user=Depends(current_user), db=Depends(get_db)):
    return ok(list_profiles(db, user.session_company_id, (request.query_params.get("doc_code") or "").strip()))


@router.post("/export-profiles")
def create_export_profile(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = save_profile(db, user, user.session_company_id, None, payload)
    return ok({"id": row.id, "version": row.version})


@router.put("/export-profiles/{row_id}")
def update_export_profile(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = save_profile(db, user, user.session_company_id, row_id, payload)
    return ok({"id": row.id, "version": row.version})


@router.delete("/export-profiles/{row_id}")
def delete_export_profile(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    remove_profile(db, user, user.session_company_id, row_id, version)
    return ok({"ok": True})


@router.post("/export-profiles/upload")
async def upload_export_template(file: UploadFile = File(...), user=Depends(current_user)):
    content = await file.read()
    path = save_upload(file.filename or "", content)
    return ok({"path": path})


@router.get("/users")
def list_users(request: Request, user=Depends(current_user), db=Depends(get_db)):
    query = db.query(SysUser).filter(SysUser.deleted_at.is_(None))
    if not user.is_super_admin:
        ids = [r.employee_id for r in db.query(SysUserCompany).filter(SysUserCompany.company_id == user.session_company_id).all()]
        query = query.filter(SysUser.employee_id.in_(ids or ["-"]))
    else:
        # 当前公司关系内的用户，超级管理员另见全部
        if request.query_params.get("scope") != "all":
            ids = [r.employee_id for r in db.query(SysUserCompany).filter(SysUserCompany.company_id == user.session_company_id).all()]
            query = query.filter(or_(SysUser.employee_id.in_(ids or ["-"]), SysUser.is_super_admin.is_(True)))
    if request.query_params.get("status"):
        query = query.filter(SysUser.status == request.query_params.get("status"))
    keyword = (request.query_params.get("keyword") or "").strip()
    rows = query.order_by(SysUser.id).all()
    if keyword:
        rows = [row for row in rows if keyword in row.employee_id or keyword in row.login_name or keyword in row.name]
    if request.query_params.get("role"):
        rows = [row for row in rows if (row.role_text or "") == request.query_params.get("role")]
    items = []
    for row in rows:
        rels = db.query(SysUserCompany).filter(SysUserCompany.employee_id == row.employee_id).all()
        items.append({
            "id": row.id, "version": row.version, "employee_id": row.employee_id, "login_name": row.login_name,
            "name": row.name, "role_text": row.role_text or "", "status": row.status,
            "is_super_admin": bool(row.is_super_admin),
            "can_import_overwrite": bool(row.is_super_admin or row.can_import_overwrite),
            "companies": [rel.company_id for rel in rels],
            "default_company_id": next((rel.company_id for rel in rels if rel.is_default), None),
        })
    chunk, total, page_no, size = _slice(items, request)
    return page(chunk, total, page_no, size)


def _set_user_companies(db, employee_id, company_ids, default_id):
    db.query(SysUserCompany).filter(SysUserCompany.employee_id == employee_id).delete()
    company_ids = [int(item) for item in company_ids]
    if not company_ids:
        raise BizError("至少选择一个公司")
    if int(default_id) not in company_ids:
        raise BizError("默认公司必须在可访问公司中")
    for company_id in company_ids:
        db.add(SysUserCompany(employee_id=employee_id, company_id=company_id, is_default=company_id == int(default_id)))


@router.post("/users")
def create_user(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    employee_id = (payload.get("employee_id") or "").strip()
    login_name = (payload.get("login_name") or "").strip()
    name = (payload.get("name") or "").strip()
    if not employee_id or not login_name or not name:
        raise BizError("员工编号、登录名、姓名不能为空")
    if db.query(SysUser).filter(SysUser.employee_id == employee_id).first() or db.query(SysUser).filter(SysUser.login_name == login_name).first():
        raise BizError(MSG_CODE)
    password = payload.get("password") or "123456"
    if len(password) < min_password(db):
        raise BizError(f"密码至少 {min_password(db)} 位")
    row = SysUser(
        employee_id=employee_id, login_name=login_name, name=name, password_hash=hash_password(password),
        role_text=payload.get("role_text") or "", status=payload.get("status") or "启用",
        is_super_admin=False, can_import_overwrite=bool(payload.get("can_import_overwrite")),
        failed_login_count=0, auth_version=1, version=1, created_by=user.employee_id, updated_by=user.employee_id,
        created_at=now(), updated_at=now(),
    )
    db.add(row)
    db.flush()
    _set_user_companies(db, employee_id, payload.get("companies") or [user.session_company_id], payload.get("default_company_id") or user.session_company_id)
    op_log(db, user, user.session_company_id, "新增", "user", employee_id, {"name": name})
    return ok({"id": row.id, "version": row.version})


@router.put("/users/{row_id}")
def update_user(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = db.get(SysUser, row_id)
    if row is None or row.deleted_at:
        raise BizError("数据不存在")
    ensure_version(row, payload.get("version"))
    if payload.get("status") == "停用" and row.status != "停用":
        row.auth_version = int(row.auth_version) + 1
    row.name = payload.get("name") or row.name
    row.role_text = payload.get("role_text") or ""
    row.status = payload.get("status") or row.status
    if not row.is_super_admin:
        row.can_import_overwrite = bool(payload.get("can_import_overwrite"))
        _set_user_companies(db, row.employee_id, payload.get("companies") or [user.session_company_id], payload.get("default_company_id") or user.session_company_id)
    bump(row, user.employee_id)
    return ok({"id": row.id, "version": row.version})


@router.put("/users/{row_id}/reset-password")
def reset_password(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = db.get(SysUser, row_id)
    if row is None or row.deleted_at:
        raise BizError("数据不存在")
    password = payload.get("password") or "123456"
    if len(password) < min_password(db):
        raise BizError(f"密码至少 {min_password(db)} 位")
    row.password_hash = hash_password(password)
    row.failed_login_count = 0
    row.locked_until = None
    row.auth_version = int(row.auth_version) + 1
    bump(row, user.employee_id)
    op_log(db, user, user.session_company_id, "重置密码", "user", row.employee_id, "管理员重置密码")
    return ok({"ok": True})


@router.post("/users/{row_id}/force-logout")
def force_logout(row_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = db.get(SysUser, row_id)
    if row is None or row.deleted_at:
        raise BizError("数据不存在")
    row.auth_version = int(row.auth_version) + 1
    bump(row, user.employee_id)
    op_log(db, user, user.session_company_id, "强制退出", "user", row.employee_id, "强制退出")
    return ok({"ok": True})


@router.delete("/users/{row_id}")
def delete_user(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = db.get(SysUser, row_id)
    if row is None or row.deleted_at:
        raise BizError("数据不存在")
    ensure_version(row, version)
    if row.is_super_admin or row.login_name == "admin":
        raise BizError("不能删除 admin")
    refs.refuse_user(db, row.employee_id)
    soft_delete(row, user.employee_id)
    return ok({"ok": True})


@router.post("/users/batch-delete")
def batch_users(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    rows = []
    for item in sorted(payload.get("items") or [], key=lambda row: int(row["id"])):
        row = db.get(SysUser, int(item["id"]))
        if row is None or row.deleted_at:
            raise BizError("数据不存在")
        ensure_version(row, item.get("version"))
        if row.is_super_admin or row.login_name == "admin":
            raise BizError("不能删除 admin")
        refs.refuse_user(db, row.employee_id)
        rows.append(row)
    for row in rows:
        soft_delete(row, user.employee_id)
    return ok({"count": len(rows)})


def _dict_routes(path, model):
    slug = path.strip("/").replace("-", "_")

    def _list(request: Request, user=Depends(current_user), db=Depends(get_db), model=model):
        rows = q(db, model, user.session_company_id).order_by(model.id.desc()).all()
        keyword = (request.query_params.get("keyword") or "").strip()
        items = [{"id": r.id, "version": r.version, "code": r.code, "name": r.name, "remark": r.remark or ""} for r in rows]
        if keyword:
            items = [item for item in items if keyword in item["name"] or keyword in item["code"]]
        chunk, total, page_no, size = _slice(items, request)
        return page(chunk, total, page_no, size)

    def _create(payload: dict, user=Depends(current_user), db=Depends(get_db), model=model):
        code = (payload.get("code") or "").strip()
        ensure_code_free(db, model, user.session_company_id, model.code, code)
        row = model(code=code, name=payload.get("name") or "", remark=payload.get("remark") or "")
        stamp_new(row, user, user.session_company_id)
        db.add(row)
        db.flush()
        return ok({"id": row.id, "version": row.version})

    def _update(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db), model=model):
        row = get_row(db, model, row_id, user.session_company_id)
        ensure_version(row, payload.get("version"))
        row.name = payload.get("name") or row.name
        row.remark = payload.get("remark") or ""
        bump(row, user.employee_id)
        return ok({"id": row.id, "version": row.version})

    def _delete(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db), model=model):
        row = get_row(db, model, row_id, user.session_company_id)
        ensure_version(row, version)
        soft_delete(row, user.employee_id)
        return ok({"ok": True})

    _list.__name__ = f"list_{slug}"
    _create.__name__ = f"create_{slug}"
    _update.__name__ = f"update_{slug}"
    _delete.__name__ = f"delete_{slug}"
    router.add_api_route(path, _list, methods=["GET"])
    router.add_api_route(path, _create, methods=["POST"])
    router.add_api_route(path + "/{row_id}", _update, methods=["PUT"])
    def _batch(payload: dict, user=Depends(current_user), db=Depends(get_db), model=model):
        rows = _batch_version(db, model, user.session_company_id, payload.get("items") or [])
        for row in rows:
            soft_delete(row, user.employee_id)
        return ok({"count": len(rows)})

    _batch.__name__ = f"batch_{slug}"
    router.add_api_route(path + "/{row_id}", _delete, methods=["DELETE"])
    router.add_api_route(path + "/batch-delete", _batch, methods=["POST"])


_dict_routes("/roles", SysRole)
_dict_routes("/depts", SysDept)
_dict_routes("/posts", SysPost)


@router.get("/configs")
def list_configs(user=Depends(current_user), db=Depends(get_db)):
    rows = db.query(SysConfig).filter(SysConfig.deleted_at.is_(None)).order_by(SysConfig.id).all()
    return ok([{"id": r.id, "version": r.version, "config_name": r.config_name, "config_value": r.config_value} for r in rows])


@router.post("/configs")
def create_config(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    name = (payload.get("config_name") or "").strip()
    if db.query(SysConfig).filter(SysConfig.config_name == name).first():
        raise BizError(MSG_CODE)
    row = SysConfig(config_name=name, config_value=str(payload.get("config_value") or ""), version=1, created_by=user.employee_id, updated_by=user.employee_id, created_at=now(), updated_at=now())
    db.add(row)
    db.flush()
    return ok({"id": row.id, "version": row.version})


@router.put("/configs/{row_id}")
def update_config(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = db.get(SysConfig, row_id)
    if row is None or row.deleted_at:
        raise BizError("数据不存在")
    ensure_version(row, payload.get("version"))
    row.config_value = str(payload.get("config_value") or "")
    bump(row, user.employee_id)
    return ok({"id": row.id, "version": row.version})


@router.get("/other-bills")
def list_other(request: Request, user=Depends(current_user), db=Depends(get_db)):
    query = q(db, OtherBill, user.session_company_id)
    if request.query_params.get("direction"):
        query = query.filter(OtherBill.direction == request.query_params.get("direction"))
    keyword = (request.query_params.get("keyword") or "").strip()
    rows = query.order_by(OtherBill.id.desc()).all()
    items = [{"id": r.id, "version": r.version, "bill_code": r.bill_code, "bill_date": dump(r.bill_date), "direction": r.direction, "party_name": r.party_name or "", "contract_code": r.contract_code or "", "amount": money_str(r.amount), "account_name": r.account_name or "", "remark": r.remark or "", "created_by": r.created_by} for r in rows]
    if keyword:
        items = [item for item in items if keyword in item["party_name"] or keyword in item["contract_code"] or keyword in item["bill_code"]]
    chunk, total, page_no, size = _slice(items, request)
    amount = sum((D(item["amount"]) for item in items), ZERO)
    return page(chunk, total, page_no, size, sums={"amount": money_str(amount)})


@router.post("/other-bills")
def create_other(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    from ..services.util import next_daily_code
    code = (payload.get("bill_code") or "").strip() or next_daily_code(db, OtherBill, user.session_company_id, OtherBill.bill_code, "SR" if payload.get("direction") == "income" else "ZC")
    ensure_code_free(db, OtherBill, user.session_company_id, OtherBill.bill_code, code)
    amount = D(payload.get("amount") or 0)
    if amount <= 0:
        raise BizError("金额必须大于 0")
    row = OtherBill(bill_code=code, bill_date=date.fromisoformat(payload.get("bill_date")), direction=payload.get("direction"), party_name=payload.get("party_name") or "", contract_code=payload.get("contract_code") or "", amount=amount, account_name=payload.get("account_name") or "", remark=payload.get("remark") or "")
    stamp_new(row, user, user.session_company_id)
    db.add(row)
    db.flush()
    op_log(db, user, user.session_company_id, "新增", "other", row.id, {"code": code})
    return ok({"id": row.id, "version": row.version})


@router.put("/other-bills/{row_id}")
def update_other(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, OtherBill, row_id, user.session_company_id)
    ensure_creator(row, user)
    ensure_version(row, payload.get("version"))
    amount = D(payload.get("amount") or 0)
    if amount <= 0:
        raise BizError("金额必须大于 0")
    row.bill_date = date.fromisoformat(payload.get("bill_date"))
    row.party_name = payload.get("party_name") or ""
    row.contract_code = payload.get("contract_code") or ""
    row.amount = amount
    row.account_name = payload.get("account_name") or ""
    row.remark = payload.get("remark") or ""
    bump(row, user.employee_id)
    return ok({"id": row.id, "version": row.version})


@router.delete("/other-bills/{row_id}")
def delete_other(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, OtherBill, row_id, user.session_company_id)
    ensure_creator(row, user)
    ensure_version(row, version)
    soft_delete(row, user.employee_id)
    return ok({"ok": True})


@router.post("/other-bills/batch-delete")
def batch_other(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    rows = _batch_version(db, OtherBill, user.session_company_id, payload.get("items") or [])
    for row in rows:
        ensure_creator(row, user)
        soft_delete(row, user.employee_id)
    return ok({"count": len(rows)})


@router.get("/stocks")
def list_stocks(request: Request, user=Depends(current_user), db=Depends(get_db)):
    query = q(db, Stock, user.session_company_id)
    if request.query_params.get("warehouse_id"):
        query = query.filter(Stock.warehouse_id == int(request.query_params.get("warehouse_id")))
    if request.query_params.get("material_code"):
        query = query.filter(Stock.material_code == request.query_params.get("material_code"))
    rows = query.order_by(Stock.material_code).all()
    wh = {w.id: w.name for w in q(db, Warehouse, user.session_company_id).all()}
    items = [{"id": r.id, "version": r.version, "warehouse_id": r.warehouse_id, "warehouse_name": wh.get(r.warehouse_id, ""), "material_code": r.material_code, "goods_code": r.goods_code or "", "goods_name": r.goods_name or "", "unit": r.unit or "", "qty": qty_str(r.qty), "cost": money_str(r.cost) if r.cost is not None else ""} for r in rows]
    chunk, total, page_no, size = _slice(items, request)
    return page(chunk, total, page_no, size)


@router.delete("/stocks/{row_id}")
def delete_stock(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, Stock, row_id, user.session_company_id)
    ensure_version(row, version)
    if D(row.qty) != 0:
        raise BizError("库存余额不为零，不能删除")
    material_code = row.material_code
    stock_id = row.id
    soft_delete(row, user.employee_id)
    op_log(db, user, user.session_company_id, "删除", "stock", stock_id, {"material_code": material_code})
    return ok({"ok": True})


@router.post("/stocks/batch-delete")
def batch_stock(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    rows = _batch_version(db, Stock, user.session_company_id, payload.get("items") or [])
    busy = [row.material_code for row in rows if D(row.qty) != 0]
    if busy:
        raise BizError(f"物料 {'、'.join(busy)} 库存余额不为零，不能删除")
    for row in rows:
        material_code = row.material_code
        stock_id = row.id
        soft_delete(row, user.employee_id)
        op_log(db, user, user.session_company_id, "删除", "stock", stock_id, {"material_code": material_code})
    return ok({"count": len(rows)})


@router.get("/transfer-bills")
def list_transfer(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = q(db, TransferBill, user.session_company_id).order_by(TransferBill.id.desc()).all()
    wh = {w.id: w.name for w in db.query(Warehouse).filter(Warehouse.company_id == user.session_company_id).all()}
    items = [{"id": r.id, "version": r.version, "bill_code": r.bill_code, "bill_date": dump(r.bill_date), "warehouse_out": r.warehouse_out, "warehouse_out_name": wh.get(r.warehouse_out, ""), "warehouse_in": r.warehouse_in, "warehouse_in_name": wh.get(r.warehouse_in, ""), "material_code": r.material_code, "qty": qty_str(r.qty), "remark": r.remark or "", "created_by": r.created_by} for r in rows]
    chunk, total, page_no, size = _slice(items, request)
    return page(chunk, total, page_no, size)


@router.post("/transfer-bills")
def create_transfer(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    from ..services.util import next_daily_code
    code = (payload.get("bill_code") or "").strip() or next_daily_code(db, TransferBill, user.session_company_id, TransferBill.bill_code, "DB")
    ensure_code_free(db, TransferBill, user.session_company_id, TransferBill.bill_code, code)
    get_row(db, Warehouse, payload.get("warehouse_out"), user.session_company_id)
    get_row(db, Warehouse, payload.get("warehouse_in"), user.session_company_id)
    row = TransferBill(bill_code=code, bill_date=date.fromisoformat(payload.get("bill_date")), warehouse_out=int(payload.get("warehouse_out")), warehouse_in=int(payload.get("warehouse_in")), material_code=payload.get("material_code"), qty=D(payload.get("qty")), remark=payload.get("remark") or "")
    if D(row.qty) <= 0:
        raise BizError("数量必须大于 0")
    stamp_new(row, user, user.session_company_id)
    db.add(row)
    db.flush()
    op_log(db, user, user.session_company_id, "新增", "transfer", row.id, {"code": code})
    return ok({"id": row.id, "version": row.version})


@router.put("/transfer-bills/{row_id}")
def update_transfer(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, TransferBill, row_id, user.session_company_id)
    ensure_creator(row, user)
    ensure_version(row, payload.get("version"))
    code = (payload.get("bill_code") or row.bill_code or "").strip()
    if not code:
        raise BizError("单据编号不能为空")
    if code != row.bill_code:
        ensure_code_free(db, TransferBill, user.session_company_id, TransferBill.bill_code, code, row.id)
    warehouse_out = int(payload.get("warehouse_out") or row.warehouse_out)
    warehouse_in = int(payload.get("warehouse_in") or row.warehouse_in)
    get_row(db, Warehouse, warehouse_out, user.session_company_id)
    get_row(db, Warehouse, warehouse_in, user.session_company_id)
    material_code = (payload.get("material_code") or row.material_code or "").strip()
    if not material_code:
        raise BizError("物料编号不能为空")
    qty = D(payload.get("qty") if payload.get("qty") not in (None, "") else row.qty)
    if qty <= 0:
        raise BizError("数量必须大于 0")
    row.bill_code = code
    row.bill_date = parse_date(payload.get("bill_date")) or row.bill_date
    row.warehouse_out = warehouse_out
    row.warehouse_in = warehouse_in
    row.material_code = material_code
    row.qty = qty
    row.remark = payload.get("remark") or ""
    bump(row, user.employee_id)
    op_log(db, user, user.session_company_id, "修改", "transfer", row.id, {"code": code, "qty": qty_str(qty)})
    return ok({"id": row.id, "version": row.version})


@router.delete("/transfer-bills/{row_id}")
def delete_transfer(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, TransferBill, row_id, user.session_company_id)
    ensure_creator(row, user)
    ensure_version(row, version)
    soft_delete(row, user.employee_id)
    return ok({"ok": True})


@router.post("/transfer-bills/batch-delete")
def batch_transfer(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    rows = _batch_version(db, TransferBill, user.session_company_id, payload.get("items") or [])
    for row in rows:
        ensure_creator(row, user)
        soft_delete(row, user.employee_id)
    return ok({"count": len(rows)})


@router.get("/check-bills")
def list_checks(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = q(db, CheckBill, user.session_company_id).order_by(CheckBill.id.desc()).all()
    wh = {w.id: w.name for w in db.query(Warehouse).filter(Warehouse.company_id == user.session_company_id).all()}
    items = []
    for row in rows:
        diff = D(row.actual_qty) - D(row.book_qty)
        items.append({"id": row.id, "version": row.version, "bill_code": row.bill_code, "bill_date": dump(row.bill_date), "warehouse_id": row.warehouse_id, "warehouse_name": wh.get(row.warehouse_id, ""), "material_code": row.material_code, "book_qty": qty_str(row.book_qty), "actual_qty": qty_str(row.actual_qty), "diff_qty": qty_str(diff), "remark": row.remark or "", "created_by": row.created_by})
    chunk, total, page_no, size = _slice(items, request)
    return page(chunk, total, page_no, size)


@router.post("/check-bills")
def create_check(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    from ..services.util import next_daily_code
    code = (payload.get("bill_code") or "").strip() or next_daily_code(db, CheckBill, user.session_company_id, CheckBill.bill_code, "PD")
    ensure_code_free(db, CheckBill, user.session_company_id, CheckBill.bill_code, code)
    warehouse_id = int(payload.get("warehouse_id"))
    get_row(db, Warehouse, warehouse_id, user.session_company_id)
    stock = db.query(Stock).filter(Stock.company_id == user.session_company_id, Stock.warehouse_id == warehouse_id, Stock.material_code == payload.get("material_code"), Stock.deleted_at.is_(None)).first()
    book = D(stock.qty) if stock else ZERO
    actual_qty = D(payload.get("actual_qty") or 0)
    if actual_qty < 0:
        raise BizError("实际数量不能小于 0")
    row = CheckBill(bill_code=code, bill_date=date.fromisoformat(payload.get("bill_date")), warehouse_id=warehouse_id, material_code=payload.get("material_code"), book_qty=book, actual_qty=actual_qty, remark=payload.get("remark") or "")
    stamp_new(row, user, user.session_company_id)
    db.add(row)
    db.flush()
    op_log(db, user, user.session_company_id, "新增", "check", row.id, {"code": code, "diff": qty_str(D(row.actual_qty) - book)})
    return ok({"id": row.id, "version": row.version, "book_qty": qty_str(book)})


@router.put("/check-bills/{row_id}")
def update_check(row_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CheckBill, row_id, user.session_company_id)
    ensure_creator(row, user)
    ensure_version(row, payload.get("version"))
    code = (payload.get("bill_code") or row.bill_code or "").strip()
    if not code:
        raise BizError("单据编号不能为空")
    if code != row.bill_code:
        ensure_code_free(db, CheckBill, user.session_company_id, CheckBill.bill_code, code, row.id)
    warehouse_id = int(payload.get("warehouse_id") or row.warehouse_id)
    get_row(db, Warehouse, warehouse_id, user.session_company_id)
    material_code = (payload.get("material_code") or row.material_code or "").strip()
    if not material_code:
        raise BizError("物料编号不能为空")
    actual_qty = D(payload.get("actual_qty") if payload.get("actual_qty") not in (None, "") else row.actual_qty)
    if actual_qty < 0:
        raise BizError("实际数量不能小于 0")
    if warehouse_id != row.warehouse_id or material_code != row.material_code:
        stock = db.query(Stock).filter(Stock.company_id == user.session_company_id, Stock.warehouse_id == warehouse_id, Stock.material_code == material_code, Stock.deleted_at.is_(None)).first()
        row.book_qty = D(stock.qty) if stock else ZERO
    row.bill_code = code
    row.bill_date = parse_date(payload.get("bill_date")) or row.bill_date
    row.warehouse_id = warehouse_id
    row.material_code = material_code
    row.actual_qty = actual_qty
    row.remark = payload.get("remark") or ""
    bump(row, user.employee_id)
    op_log(db, user, user.session_company_id, "修改", "check", row.id, {"code": code, "diff": qty_str(actual_qty - D(row.book_qty))})
    return ok({"id": row.id, "version": row.version})


@router.delete("/check-bills/{row_id}")
def delete_check(row_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CheckBill, row_id, user.session_company_id)
    ensure_creator(row, user)
    ensure_version(row, version)
    soft_delete(row, user.employee_id)
    return ok({"ok": True})


@router.post("/check-bills/batch-delete")
def batch_checks(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    rows = _batch_version(db, CheckBill, user.session_company_id, payload.get("items") or [])
    for row in rows:
        ensure_creator(row, user)
        soft_delete(row, user.employee_id)
    return ok({"count": len(rows)})


def _signed(db, company_id, direction=None):
    query = q(db, Contract, company_id).filter(Contract.status == "已签订")
    if direction:
        query = query.filter(Contract.direction == direction)
    return query.all()


@router.get("/stats/home")
def stats_home(request: Request, user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    sales = _signed(db, company_id, "sale")
    purchases = _signed(db, company_id, "purchase")
    sale_amount = sum((D(row.amount) for row in sales), ZERO)
    purchase_amount = sum((D(row.amount) for row in purchases), ZERO)
    received = sum((D(row.settled_sum) for row in sales), ZERO)
    paid = sum((D(row.settled_sum) for row in purchases), ZERO)
    income = sum((D(row.amount) for row in q(db, OtherBill, company_id).filter(OtherBill.direction == "income").all()), ZERO)
    expense = sum((D(row.amount) for row in q(db, OtherBill, company_id).filter(OtherBill.direction == "expense").all()), ZERO)
    cards = {
        "销售合同金额": money_str(sale_amount),
        "累计销售金额": money_str(sale_amount),
        "已收款": money_str(received),
        "合同未收款": money_str(max0(sale_amount - received)),
        "采购合同金额": money_str(purchase_amount),
        "累计采购金额": money_str(purchase_amount),
        "已付款": money_str(paid),
        "合同毛利": money_str(sale_amount - purchase_amount - expense + income),
        "已开票": money_str(sum((D(row.total) for row in q(db, Invoice, company_id).all() if db.get(Contract, row.contract_id) and db.get(Contract, row.contract_id).status == "已签订"), ZERO)),
    }
    keyword = (request.query_params.get("keyword") or "").strip()
    recent_query = q(db, Contract, company_id).order_by(Contract.id.desc())
    recent = []
    for row in recent_query.limit(30).all():
        if keyword and keyword not in row.contract_code and keyword not in (row.name or ""):
            continue
        recent.append({"contract_code": row.contract_code, "name": row.name, "direction": "销售" if row.direction == "sale" else "采购", "amount": money_str(row.amount)})
        if len(recent) >= 5:
            break
    return ok({"cards": cards, "recent": recent, "board": _home_board(db, company_id)})


def _same_month(value, today):
    if value is None:
        return False
    if isinstance(value, datetime):
        value = value.date()
    return value.year == today.year and value.month == today.month


def _pct(part, whole):
    if D(whole) <= 0:
        return "0.0"
    return format((D(part) / D(whole) * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), "f")


def _shift_month(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _home_board(db, company_id):
    today = date.today()
    contracts = q(db, Contract, company_id).all()
    parties = q(db, Party, company_id).all()
    invoices = q(db, Invoice, company_id).all()
    bills = q(db, SettleBill, company_id).order_by(SettleBill.id.desc()).all()
    signed = [row for row in contracts if row.status == "已签订"]
    sales = [row for row in signed if row.direction == "sale"]
    purchases = [row for row in signed if row.direction == "purchase"]
    sale_amount = sum((D(row.amount) for row in sales), ZERO)
    purchase_amount = sum((D(row.amount) for row in purchases), ZERO)
    received = sum((D(row.settled_sum) for row in sales), ZERO)
    paid = sum((D(row.settled_sum) for row in purchases), ZERO)
    done = [row for row in signed if D(row.settled_sum) >= D(row.amount)]
    customers = [row for row in parties if row.type == "customer"]
    suppliers = [row for row in parties if row.type == "supplier"]

    def invoice_sum(direction, month_only=False):
        total = ZERO
        for row in invoices:
            if row.direction != direction:
                continue
            contract = db.get(Contract, row.contract_id)
            if not contract or contract.deleted_at is not None or contract.status != "已签订":
                continue
            if month_only and not _same_month(row.invoice_date, today):
                continue
            total += D(row.total)
        return total

    def bill_month(direction):
        return sum((D(row.amount) for row in bills if row.direction == direction and _same_month(row.bill_date, today)), ZERO)

    invoiced_out = invoice_sum("output")
    invoiced_in = invoice_sum("input")
    months = []
    buckets = {}
    for offset in range(11, -1, -1):
        year, month = _shift_month(today.year, today.month, -offset)
        key = f"{year}-{month:02d}"
        months.append(key)
        buckets[key] = {"month": key, "label": f"{year}年{month:02d}月", "sale": ZERO, "purchase": ZERO}
    for row in signed:
        anchor = row.sign_date or (row.created_at.date() if row.created_at else None)
        if not anchor:
            continue
        key = f"{anchor.year}-{anchor.month:02d}"
        if key not in buckets:
            continue
        buckets[key]["sale" if row.direction == "sale" else "purchase"] += D(row.amount)
    trend = []
    for key in months:
        slot = buckets[key]
        trend.append({"month": slot["month"], "label": slot["label"], "sale": money_str(slot["sale"]), "purchase": money_str(slot["purchase"])})

    status_rows = []
    for name in ("已签订", "未签订", "已终止"):
        group = [row for row in contracts if row.status == name]
        if name == "已终止" and not group:
            continue
        status_rows.append({
            "name": name,
            "count": len(group),
            "amount": money_str(sum((D(row.amount) for row in group), ZERO)),
            "settled": money_str(sum((D(row.settled_sum) for row in group), ZERO)),
        })

    def recent_contracts(direction):
        rows = [row for row in contracts if row.direction == direction]
        rows.sort(key=lambda row: row.id, reverse=True)
        items = []
        for row in rows[:5]:
            party = db.get(Party, row.party_id)
            items.append({
                "id": row.id,
                "name": row.name,
                "amount": money_str(row.amount),
                "party_name": party.name if party else (row.party_name or ""),
                "date": dump(row.sign_date) or (row.created_at.strftime("%Y-%m-%d") if row.created_at else ""),
                "status": row.status,
            })
        return items

    def recent_bills(direction):
        items = []
        for row in bills:
            if row.direction != direction:
                continue
            items.append({
                "id": row.id,
                "bill_code": row.bill_code,
                "amount": money_str(row.amount),
                "bill_date": dump(row.bill_date),
                "party_name": row.party_name or "",
            })
            if len(items) >= 5:
                break
        return items

    reminders = []
    labels = {"sale": "销售合同到期", "purchase": "采购合同到期", "output": "销项发票到期", "input": "进项发票到期"}
    for contract in contracts:
        if not contract.end_date:
            continue
        days = (contract.end_date - today).days
        if days > 30:
            continue
        record = db.query(ReminderRecord).filter(ReminderRecord.company_id == company_id, ReminderRecord.biz_type == "contract", ReminderRecord.biz_code == contract.contract_code, ReminderRecord.deleted_at.is_(None)).first()
        if record and record.status in ("confirmed", "ignored"):
            continue
        party = db.get(Party, contract.party_id)
        reminders.append({
            "kind": contract.direction,
            "label": labels[contract.direction],
            "name": contract.name,
            "code": contract.contract_code,
            "party_name": party.name if party else (contract.party_name or ""),
            "due_date": dump(contract.end_date),
            "days": days,
            "target": "contract",
            "id": contract.id,
        })
    for invoice in invoices:
        if not invoice.invoice_date:
            continue
        days = (invoice.invoice_date - today).days
        if days > 30:
            continue
        kind = "output" if invoice.direction == "output" else "input"
        record = db.query(ReminderRecord).filter(ReminderRecord.company_id == company_id, ReminderRecord.biz_type == "invoice", ReminderRecord.biz_code == invoice.invoice_no, ReminderRecord.deleted_at.is_(None)).first()
        if record and record.status in ("confirmed", "ignored"):
            continue
        party = db.get(Party, invoice.party_id)
        reminders.append({
            "kind": kind,
            "label": labels[kind],
            "name": invoice.invoice_no,
            "code": invoice.bill_code or invoice.invoice_no,
            "party_name": party.name if party else (invoice.party_name or ""),
            "due_date": dump(invoice.invoice_date),
            "days": days,
            "target": "invoice",
            "id": invoice.id,
            "direction": "output" if kind == "output" else "input",
        })
    reminders.sort(key=lambda row: row["days"])

    return {
        "counts": {
            "contracts": len(contracts),
            "contracts_month": sum(1 for row in contracts if _same_month(row.created_at, today)),
            "done": len(done),
            "done_rate": _pct(len(done), len(contracts)),
            "customers": len(customers),
            "customers_month": sum(1 for row in customers if _same_month(row.created_at, today)),
            "suppliers": len(suppliers),
            "suppliers_month": sum(1 for row in suppliers if _same_month(row.created_at, today)),
        },
        "money": {
            "received": money_str(received),
            "received_month": money_str(bill_month("receipt")),
            "received_rate": _pct(received, sale_amount),
            "invoiced_out": money_str(invoiced_out),
            "invoiced_out_month": money_str(invoice_sum("output", True)),
            "invoiced_out_rate": _pct(invoiced_out, sale_amount),
            "paid": money_str(paid),
            "paid_month": money_str(bill_month("payment")),
            "paid_rate": _pct(paid, purchase_amount),
            "invoiced_in": money_str(invoiced_in),
            "invoiced_in_month": money_str(invoice_sum("input", True)),
            "invoiced_in_rate": _pct(invoiced_in, purchase_amount),
        },
        "reminders": reminders[:40],
        "trend": trend,
        "status": status_rows,
        "contracts": {"sale": recent_contracts("sale"), "purchase": recent_contracts("purchase")},
        "bills": {"receipt": recent_bills("receipt"), "payment": recent_bills("payment")},
    }


@router.get("/stats/overview")
def stats_overview(user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    sales = _signed(db, company_id, "sale")
    purchases = _signed(db, company_id, "purchase")
    sale_amount = sum((D(row.amount) for row in sales), ZERO)
    purchase_amount = sum((D(row.amount) for row in purchases), ZERO)
    received = sum((D(row.settled_sum) for row in sales), ZERO)
    paid = sum((D(row.settled_sum) for row in purchases), ZERO)
    income = sum((D(row.amount) for row in q(db, OtherBill, company_id).filter(OtherBill.direction == "income").all()), ZERO)
    expense = sum((D(row.amount) for row in q(db, OtherBill, company_id).filter(OtherBill.direction == "expense").all()), ZERO)
    invoiced = ZERO
    for row in q(db, Invoice, company_id).all():
        contract = db.get(Contract, row.contract_id)
        if contract and contract.status == "已签订":
            invoiced += D(row.total)
    return ok({
        "cards": {
            "销售合同金额": money_str(sale_amount),
            "累计销售金额": money_str(sale_amount),
            "已收款": money_str(received),
            "已开票": money_str(invoiced),
            "采购合同金额": money_str(purchase_amount),
            "累计采购金额": money_str(purchase_amount),
            "已付款": money_str(paid),
            "合同毛利": money_str(sale_amount - purchase_amount - expense + income),
        }
    })


@router.get("/stats/customer")
def stats_customer(request: Request, user=Depends(current_user), db=Depends(get_db)):
    return ok(_party_stats(db, user.session_company_id, "sale", request.query_params.get("keyword")))


@router.get("/stats/supplier")
def stats_supplier(request: Request, user=Depends(current_user), db=Depends(get_db)):
    return ok(_party_stats(db, user.session_company_id, "purchase", request.query_params.get("keyword")))


def _party_stats(db, company_id, direction, keyword):
    rows = _signed(db, company_id, direction)
    grouped = {}
    for row in rows:
        slot = grouped.setdefault(row.party_id, {"count": 0, "amount": ZERO, "settled": ZERO, "name": row.party_name or ""})
        slot["count"] += 1
        slot["amount"] += D(row.amount)
        slot["settled"] += D(row.settled_sum)
        party = db.get(Party, row.party_id)
        if party:
            slot["name"] = party.name
    items = []
    for party_id, slot in grouped.items():
        if keyword and keyword not in slot["name"]:
            continue
        done = slot["settled"] >= slot["amount"] and slot["amount"] > 0 or (slot["amount"] == 0 and slot["settled"] >= 0 and slot["count"])
        status = "已完成" if slot["settled"] >= slot["amount"] else "进行中"
        items.append({"party_id": party_id, "name": slot["name"], "count": slot["count"], "amount": money_str(slot["amount"]), "settled": money_str(slot["settled"]), "status": status})
    return items


def _month_key(plan_date: date | None, today: date):
    if plan_date is None:
        return None
    diff = (plan_date.year - today.year) * 12 + (plan_date.month - today.month)
    if diff <= 0:
        return "this"
    return {1: "next", 2: "m2", 3: "m3", 4: "m4", 5: "m5"}.get(diff, "later")


@router.get("/pending")
def pending(request: Request, user=Depends(current_user), db=Depends(get_db)):
    direction = request.query_params.get("direction") or "purchase"
    company_id = user.session_company_id
    months = [item for item in (request.query_params.get("months") or "").split(",") if item]
    party_id = request.query_params.get("party_id")
    today = date.today()
    contracts = q(db, Contract, company_id).filter(Contract.direction == direction, Contract.status.in_(["已签订", "已终止"])).all()
    items = []
    stage_count = 0
    stage_sum = ZERO
    for contract in contracts:
        if party_id and str(contract.party_id) != str(party_id):
            continue
        stages = []
        for stage in calc.stages_of(db, contract.id):
            remain = D(stage.plan_amount) - D(stage.settled_amount)
            if remain <= 0:
                continue
            key = _month_key(stage.plan_date, today)
            if months and key not in months:
                continue
            if not months or key in months:
                if months and key is None:
                    continue
                stages.append(stage)
        if not stages:
            continue
        balance = sum((max0(D(stage.plan_amount) - D(stage.settled_amount)) for stage in stages), ZERO)
        stage_count += len(stages)
        stage_sum += balance
        overdue = any(stage.plan_date and stage.plan_date < today for stage in stages)
        details = []
        remarks = []
        for stage in stages:
            remain = max0(D(stage.plan_amount) - D(stage.settled_amount))
            when = dump(stage.plan_date) if stage.plan_date else "未设截止日"
            details.append(f"{stage.name} {money_str(remain)}（{when}）")
            remarks.append(stage.remark or "")
        party = db.get(Party, contract.party_id)
        items.append({
            "id": contract.id,
            "contract_code": contract.contract_code,
            "name": contract.name,
            "party_name": party.name if party else contract.party_name,
            "balance": money_str(balance),
            "detail": "\n".join(details),
            "remark": "\n".join(remarks),
            "overdue": "逾期" if overdue else "",
            "status": contract.status,
        })
    chunk, total, page_no, size = _slice(items, request)
    label = "未付" if direction == "purchase" else "未收"
    return page(chunk, total, page_no, size, summary={"stage_count": stage_count, "amount": money_str(stage_sum), "label": label})


def _reminder_rows(db, company_id, today):
    tabs = {"sale": [], "purchase": [], "output": [], "input": []}
    for contract in q(db, Contract, company_id).all():
        if not contract.end_date or contract.end_date > today:
            continue
        record = db.query(ReminderRecord).filter(ReminderRecord.company_id == company_id, ReminderRecord.biz_type == "contract", ReminderRecord.biz_code == contract.contract_code, ReminderRecord.deleted_at.is_(None)).first()
        status = {"confirmed": "已确认", "ignored": "已忽略"}.get(record.status, "未处理") if record else "未处理"
        party = db.get(Party, contract.party_id)
        tabs[contract.direction].append({
            "biz_type": "contract", "direction": contract.direction, "biz_code": contract.contract_code,
            "name": contract.name, "type_name": contract.type_name or "", "party_name": party.name if party else contract.party_name,
            "amount": money_str(contract.amount), "biz_status": contract.status, "due_date": dump(contract.end_date),
            "remain_days": 0, "status": status, "remark": record.remark if record else "",
        })
    for invoice in q(db, Invoice, company_id).all():
        if not invoice.invoice_date or invoice.invoice_date > today:
            continue
        direction = "output" if invoice.direction == "output" else "input"
        record = db.query(ReminderRecord).filter(ReminderRecord.company_id == company_id, ReminderRecord.biz_type == "invoice", ReminderRecord.biz_code == invoice.invoice_no, ReminderRecord.deleted_at.is_(None)).first()
        status = {"confirmed": "已确认", "ignored": "已忽略"}.get(record.status, "未处理") if record else "未处理"
        party = db.get(Party, invoice.party_id)
        tabs[direction].append({
            "biz_type": "invoice", "direction": "sale" if direction == "output" else "purchase", "biz_code": invoice.invoice_no,
            "name": invoice.invoice_no, "type_name": invoice.invoice_type, "party_name": party.name if party else invoice.party_name,
            "amount": money_str(invoice.total), "biz_status": invoice.invoice_type, "due_date": dump(invoice.invoice_date),
            "remain_days": 0, "status": status, "remark": record.remark if record else "",
        })
    return tabs


@router.get("/reminders")
def reminders(request: Request, user=Depends(current_user), db=Depends(get_db)):
    tabs = _reminder_rows(db, user.session_company_id, date.today())
    tab = request.query_params.get("tab") or "sale"
    rows = tabs.get(tab, [])
    keyword = (request.query_params.get("keyword") or "").strip()
    status = request.query_params.get("status")
    if keyword:
        rows = [row for row in rows if keyword in row["biz_code"] or keyword in (row["name"] or "")]
    if status:
        rows = [row for row in rows if row["status"] == status]
    counts = {key: sum(1 for row in value if row["status"] == "未处理") for key, value in tabs.items()}
    chunk, total, page_no, size = _slice(rows, request)
    return page(chunk, total, page_no, size, counts=counts, bell=sum(counts.values()))


@router.post("/reminders/check")
def check_reminders(user=Depends(current_user), db=Depends(get_db)):
    tabs = _reminder_rows(db, user.session_company_id, date.today())
    counts = {key: sum(1 for row in value if row["status"] == "未处理") for key, value in tabs.items()}
    return ok({"counts": counts, "bell": sum(counts.values()), "tabs": {key: value[:50] for key, value in tabs.items()}})


@router.post("/reminders/mark")
def mark_reminder(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    status = "confirmed" if payload.get("status") in ("confirmed", "已确认") else "ignored"
    row = db.query(ReminderRecord).filter(
        ReminderRecord.company_id == user.session_company_id,
        ReminderRecord.biz_type == payload.get("biz_type"),
        ReminderRecord.biz_code == payload.get("biz_code"),
        ReminderRecord.deleted_at.is_(None),
    ).first()
    if row is None:
        row = ReminderRecord(
            biz_type=payload.get("biz_type"),
            direction=payload.get("direction") or "sale",
            biz_code=payload.get("biz_code"),
            status="unhandled",
        )
        stamp_new(row, user, user.session_company_id)
        db.add(row)
    row.status = status
    row.handled_by = user.employee_id
    row.handled_at = now()
    row.remark = payload.get("remark") or row.remark
    return ok({"ok": True})


@router.get("/login-logs")
def login_logs(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = db.query(LoginLog).order_by(LoginLog.id.desc()).all()
    keyword = (request.query_params.get("keyword") or "").strip()
    items = [{"id": r.id, "user": r.user, "login_time": dump(r.login_time), "ip": r.ip, "result": r.result} for r in rows]
    if keyword:
        items = [item for item in items if keyword in item["user"]]
    if request.query_params.get("result"):
        items = [item for item in items if item["result"] == request.query_params.get("result")]
    chunk, total, page_no, size = _slice(items, request)
    return page(chunk, total, page_no, size)


@router.get("/op-logs")
def op_logs(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = db.query(OpLog).filter(or_(OpLog.company_id == user.session_company_id, OpLog.company_id.is_(None))).order_by(OpLog.id.desc()).all()
    names = user_names(db, [r.operator for r in rows])
    items = [{"id": r.id, "user": name_of(names, r.operator), "operator": r.operator, "action": r.action, "biz_type": r.biz_type, "biz_id": r.biz_id, "detail": r.detail or "", "time": dump(r.created_at), "ip": r.ip} for r in rows]
    keyword = (request.query_params.get("keyword") or "").strip()
    if keyword:
        items = [item for item in items if keyword in item["user"] or keyword in item["action"] or keyword in item["detail"]]
    chunk, total, page_no, size = _slice(items, request)
    return page(chunk, total, page_no, size)


@router.get("/next-code/{module}")
def next_code(module: str, request: Request, user=Depends(current_user), db=Depends(get_db)):
    from ..services.util import next_contract_code, next_daily_code
    company_id = user.session_company_id
    direction = request.query_params.get("direction") or "purchase"
    if module == "contract":
        code = next_contract_code(db, company_id, "sale" if direction == "sale" else "purchase")
    elif module == "wms":
        code = next_daily_code(db, WmsBill, company_id, WmsBill.bill_code, "CK" if direction == "sale" else "RK")
    elif module == "invoice":
        code = next_daily_code(db, Invoice, company_id, Invoice.bill_code, "XX" if direction == "sale" else "JX")
    elif module == "settle":
        code = next_daily_code(db, SettleBill, company_id, SettleBill.bill_code, "SK" if direction == "sale" else "FK")
    elif module == "other":
        code = next_daily_code(db, OtherBill, company_id, OtherBill.bill_code, "SR" if direction == "income" else "ZC")
    elif module == "transfer":
        code = next_daily_code(db, TransferBill, company_id, TransferBill.bill_code, "DB")
    elif module == "check":
        code = next_daily_code(db, CheckBill, company_id, CheckBill.bill_code, "PD")
    else:
        raise BizError("未知编号类型")
    return ok({"code": code})


@router.get("/supplier-detail")
def supplier_detail(request: Request, user=Depends(current_user), db=Depends(get_db)):
    company_id = user.session_company_id
    contracts = _signed(db, company_id, "purchase")
    today = date.today()
    grouped = {}
    for contract in contracts:
        party = db.get(Party, contract.party_id)
        slot = grouped.setdefault(contract.party_id, {"party_id": contract.party_id, "name": party.name if party else contract.party_name, "amount": ZERO, "paid": ZERO, "count": 0, "overdue": False, "contracts": []})
        slot["amount"] += D(contract.amount)
        slot["paid"] += D(contract.settled_sum)
        slot["count"] += 1
        stages = calc.stages_of(db, contract.id)
        contract_overdue = any(stage.plan_date and stage.plan_date < today and D(stage.plan_amount) > D(stage.settled_amount) for stage in stages)
        slot["overdue"] = slot["overdue"] or contract_overdue
        unpaid = max0(D(contract.amount) - D(contract.settled_sum))
        stage_lines = []
        for stage in stages:
            stage_lines.append({
                "name": stage.name,
                "plan_date": dump(stage.plan_date) or "未设截止日",
                "paid": money_str(stage.settled_amount),
                "unpaid": money_str(max0(D(stage.plan_amount) - D(stage.settled_amount))),
            })
        slot["contracts"].append({
            "id": contract.id,
            "contract_code": contract.contract_code,
            "name": contract.name,
            "amount": money_str(contract.amount),
            "paid": money_str(contract.settled_sum),
            "unpaid": money_str(unpaid),
            "pay_status": calc.pay_label("purchase", contract.settled_sum, contract.amount),
            "overdue": "有逾期" if contract_overdue else "无",
            "sign_date": dump(contract.sign_date),
            "stages": stage_lines,
        })
    suppliers = []
    for slot in grouped.values():
        unpaid = max0(slot["amount"] - slot["paid"])
        suppliers.append({
            "party_id": slot["party_id"],
            "name": slot["name"],
            "amount": money_str(slot["amount"]),
            "paid": money_str(slot["paid"]),
            "unpaid": money_str(unpaid),
            "debt": "有欠款" if unpaid > 0 else "无欠款",
            "overdue": "有逾期" if slot["overdue"] else "无",
            "count": slot["count"],
        })
    party_id = request.query_params.get("party_id")
    contracts_out = []
    if party_id and int(party_id) in grouped:
        contracts_out = grouped[int(party_id)]["contracts"]
        contracts_out.sort(key=lambda item: (item["overdue"] != "有逾期", item["sign_date"] or ""))
    return ok({"suppliers": suppliers, "contracts": contracts_out})
