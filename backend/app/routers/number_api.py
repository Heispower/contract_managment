"""合同编号、发票编号。"""
from fastapi import APIRouter, Depends, Request

from ..database import get_db
from ..deps import current_user
from ..models import NumberContract, NumberEditLog, NumberInvoice
from ..response import ok, page
from ..services import numbering
from ..services.util import ensure_version, get_row, q

router = APIRouter(prefix="/api/numbering")


async def _body(request: Request):
    if not request.headers.get("content-length") and not request.headers.get("transfer-encoding"):
        return {}
    data = await request.json()
    return data or {}


def _params(request: Request):
    return {key: value for key, value in request.query_params.items()}


def _logs(db, company_id, target_type, target_id):
    rows = (
        q(db, NumberEditLog, company_id)
        .filter(NumberEditLog.target_type == target_type, NumberEditLog.target_id == target_id)
        .order_by(NumberEditLog.id.desc())
        .limit(20)
        .all()
    )
    return [
        {"old_no": row.old_no, "new_no": row.new_no, "reason": row.reason, "operator_name": row.operator_name, "created_at": row.created_at}
        for row in rows
    ]


@router.get("/meta")
def numbering_meta(user=Depends(current_user), db=Depends(get_db)):
    return ok(numbering.meta(db, user.session_company_id))


@router.get("/preview")
def numbering_preview(request: Request, user=Depends(current_user), db=Depends(get_db)):
    params = _params(request)
    kind = params.get("kind") or "contract"
    company_id = user.session_company_id
    if kind == "sub":
        batch = get_row(db, numbering.NumberBatch, params.get("batch_id"), company_id)
        return ok(numbering.preview_sub(db, company_id, batch.id, batch.prefix))
    if kind == "invoice":
        rule = (params.get("number_rule") or "锰矿").strip()
        if rule not in numbering.RULE_POOL:
            from ..errors import BizError
            raise BizError("请选择编号规则")
        pool = numbering.RULE_POOL[rule]
    else:
        business = (params.get("business_type") or "锰矿").strip()
        if business not in numbering.CONTRACT_POOL:
            from ..errors import BizError
            raise BizError("业务类型只支持锰矿或铝矿")
        pool = numbering.CONTRACT_POOL[business]
    return ok(numbering.preview_number(db, company_id, pool, params.get("year")))


@router.get("/contracts")
def contract_numbers(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows, total, page_no, size = numbering.list_contract_numbers(db, user.session_company_id, _params(request))
    return page(rows, total, page_no, size)


@router.post("/contracts")
async def create_contract_number(request: Request, user=Depends(current_user), db=Depends(get_db)):
    return ok(numbering.create_contract_number(db, user, user.session_company_id, await _body(request)))


@router.get("/contracts/{row_id}")
def contract_number_detail(row_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, NumberContract, row_id, user.session_company_id)
    data = numbering._contract_dict(db, row)
    data["logs"] = _logs(db, user.session_company_id, "contract", row.id)
    return ok(data)


@router.put("/contracts/{row_id}")
async def update_contract_number(row_id: int, request: Request, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, NumberContract, row_id, user.session_company_id)
    return ok(numbering.update_contract_number(db, user, user.session_company_id, row, await _body(request)))


@router.delete("/contracts/{row_id}")
def delete_contract_number(row_id: int, request: Request, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, NumberContract, row_id, user.session_company_id)
    ensure_version(row, request.query_params.get("version"))
    numbering.delete_contract_number(db, user, user.session_company_id, row)
    return ok()


@router.post("/contracts/{row_id}/manual")
async def manual_contract_number(row_id: int, request: Request, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, NumberContract, row_id, user.session_company_id)
    return ok(numbering.manual_contract_number(db, user, user.session_company_id, row, await _body(request)))


@router.get("/invoices")
def invoice_numbers(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows, total, page_no, size = numbering.list_invoice_numbers(db, user.session_company_id, _params(request))
    return page(rows, total, page_no, size)


@router.post("/invoices")
async def create_invoice_number(request: Request, user=Depends(current_user), db=Depends(get_db)):
    return ok(numbering.create_invoice_number(db, user, user.session_company_id, await _body(request)))


@router.get("/invoices/{row_id}")
def invoice_number_detail(row_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, NumberInvoice, row_id, user.session_company_id)
    data = numbering._invoice_dict(db, row)
    data["logs"] = _logs(db, user.session_company_id, "invoice", row.id)
    return ok(data)


@router.put("/invoices/{row_id}")
async def update_invoice_number(row_id: int, request: Request, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, NumberInvoice, row_id, user.session_company_id)
    return ok(numbering.update_invoice_number(db, user, user.session_company_id, row, await _body(request)))


@router.delete("/invoices/{row_id}")
def delete_invoice_number(row_id: int, request: Request, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, NumberInvoice, row_id, user.session_company_id)
    ensure_version(row, request.query_params.get("version"))
    numbering.delete_invoice_number(db, user, user.session_company_id, row)
    return ok()


@router.post("/invoices/{row_id}/manual")
async def manual_invoice_number(row_id: int, request: Request, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, NumberInvoice, row_id, user.session_company_id)
    return ok(numbering.manual_invoice_number(db, user, user.session_company_id, row, await _body(request)))


@router.get("/batches")
def batches(user=Depends(current_user), db=Depends(get_db)):
    return ok(numbering.recent_batches(db, user.session_company_id))


@router.put("/floors")
async def save_floor(request: Request, user=Depends(current_user), db=Depends(get_db)):
    payload = await _body(request)
    pool = payload.get("pool")
    seq = numbering.parse_floor_value(pool, payload.get("value"))
    numbering.set_pool_floor(db, user.session_company_id, pool, seq)
    return ok(numbering.floor_state(db, user.session_company_id, pool))
