"""仓储入仓与报关 REST。原始物料只录一次，后续单据从报关物料生成。"""
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from ..database import get_db
from ..deps import current_user
from ..errors import BizError
from ..response import ok, page
from ..services import customs
from ..services import customs_xlsx
from ..services.export_profile import media_type_for
from ..services.form_docx import build_form
from ..services.util import ensure_version, get_row, q
from ..models import (
    BizFile,
    Company,
    CustomsClearance,
    CustomsElement,
    CustomsInvoice,
    CustomsMaterial,
    ExchangeRate,
    HsCodeLibrary,
    WarehouseReceipt,
)

router = APIRouter(prefix="/api")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ZIP = "application/zip"


def _params(request: Request, payload: dict | None = None):
    data = {key: value for key, value in request.query_params.items()}
    if payload:
        data.update({key: value for key, value in payload.items() if value not in (None, "")})
    return data


def _file(content: bytes, filename: str, media: str):
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Download-Name": quote(filename),
    }
    return StreamingResponse(BytesIO(content), media_type=media, headers=headers)


def _batch(db, user, company_id, model, items, deleter):
    rows = []
    for item in sorted(items, key=lambda row: int(row["id"])):
        row = get_row(db, model, item["id"], company_id)
        ensure_version(row, item.get("version"))
        rows.append(row)
    for row in rows:
        deleter(db, user, company_id, row)
    return len(rows)


@router.get("/warehouse/receipts")
def list_receipts(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = customs.list_receipts(db, user.session_company_id, _params(request))
    items, total, page_no, size = customs._page(rows, _params(request))
    return page(items, total, page_no, size)


@router.get("/warehouse/receipts/{receipt_id}")
def get_receipt(receipt_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, WarehouseReceipt, receipt_id, user.session_company_id)
    return ok(customs._receipt_view(db, row))


@router.post("/warehouse/receipts")
def create_receipt(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = customs.save_receipt(db, user, user.session_company_id, payload, None)
    return ok(customs._receipt_view(db, row))


@router.put("/warehouse/receipts/{receipt_id}")
def update_receipt(receipt_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, WarehouseReceipt, receipt_id, user.session_company_id)
    row = customs.save_receipt(db, user, user.session_company_id, payload, row)
    return ok(customs._receipt_view(db, row))


@router.delete("/warehouse/receipts/{receipt_id}")
def remove_receipt(receipt_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, WarehouseReceipt, receipt_id, user.session_company_id)
    ensure_version(row, version)
    customs.delete_receipt(db, user, user.session_company_id, row)
    return ok({"ok": True})


@router.post("/warehouse/receipts/batch-delete")
def batch_receipts(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    count = _batch(db, user, user.session_company_id, WarehouseReceipt, payload.get("items") or [], customs.delete_receipt)
    return ok({"count": count})


@router.post("/warehouse/receipts/import")
def import_receipts(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    return ok(customs.import_receipt_api(db, user, user.session_company_id, payload))


@router.get("/customs/materials")
def list_materials(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = customs.list_materials(db, user.session_company_id, _params(request))
    items, total, page_no, size = customs._page(rows, _params(request))
    return page(items, total, page_no, size)


@router.get("/customs/materials/options")
def material_options(request: Request, user=Depends(current_user), db=Depends(get_db)):
    return ok(customs.material_filter_options(db, user.session_company_id, _params(request)))


@router.post("/customs/materials")
def create_material(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    data = dict(payload or {})
    if not data.get("items"):
        data = {
            "receipt_no": data.get("receipt_no"),
            "receipt_date": data.get("receipt_date"),
            "supplier_id": data.get("supplier_id"),
            "supplier_name": data.get("supplier_name"),
            "contract_no": data.get("contract_no"),
            "packing_list_no": data.get("packing_list_no"),
            "remark": data.get("remark"),
            "items": [payload],
        }
    row = customs.save_receipt(db, user, user.session_company_id, data, None)
    return ok(customs._receipt_view(db, row))


@router.get("/customs/materials/{material_id}")
def get_material(material_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsMaterial, material_id, user.session_company_id)
    extra = customs._material_parents(db, [row]).get(row.id)
    data = customs._material_view(row, extra)
    data.update(customs.material_chain(db, row))
    return ok(data)


@router.put("/customs/materials/{material_id}")
def update_material(material_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsMaterial, material_id, user.session_company_id)
    row = customs.save_material(db, user, user.session_company_id, row, payload)
    extra = customs._material_parents(db, [row]).get(row.id)
    data = customs._material_view(row, extra)
    data.update(customs.material_chain(db, row))
    return ok(data)


@router.delete("/customs/materials/{material_id}")
def remove_material(material_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsMaterial, material_id, user.session_company_id)
    ensure_version(row, version)
    customs.delete_material(db, user, user.session_company_id, row)
    return ok({"ok": True})


@router.post("/customs/materials/batch-delete")
def batch_materials(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    count = _batch(db, user, user.session_company_id, CustomsMaterial, payload.get("items") or [], customs.delete_material)
    return ok({"count": count})


@router.post("/customs/materials/batch-assign")
def assign_materials(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    count = customs.batch_assign(db, user, user.session_company_id, payload)
    return ok({"count": count})


@router.post("/customs/invoices")
def create_invoice(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = customs.generate_invoice(db, user, user.session_company_id, payload)
    return ok(customs.invoice_view(db, row))


@router.post("/customs/invoices/preview")
def preview_invoice(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    return ok(customs.preview_invoice(db, user, user.session_company_id, payload))


@router.get("/customs/invoices")
def list_invoices(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = customs.list_invoices(db, user.session_company_id, _params(request))
    items, total, page_no, size = customs._page(rows, _params(request))
    return page(items, total, page_no, size)


@router.get("/customs/invoices/unused")
def unused_invoices(material_ids: str = "", user=Depends(current_user), db=Depends(get_db)):
    ids = [part.strip() for part in (material_ids or "").split(",") if part.strip()]
    return ok(customs.unused_invoices(db, user.session_company_id, ids or None))


@router.get("/customs/invoices/{invoice_id}")
def get_invoice(invoice_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsInvoice, invoice_id, user.session_company_id)
    return ok(customs.invoice_view(db, row))


@router.put("/customs/invoices/{invoice_id}")
def update_invoice(invoice_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsInvoice, invoice_id, user.session_company_id)
    customs.save_invoice(db, user, user.session_company_id, row, payload)
    return ok(customs.invoice_view(db, row))


@router.get("/customs/invoices/{invoice_id}/excel")
def excel_invoice(invoice_id: int, specificationNo: str | None = None, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsInvoice, invoice_id, user.session_company_id)
    content, filename = customs_xlsx.export_invoice_xlsx(customs.invoice_view(db, row), specificationNo)
    return _file(content, filename, XLSX)


@router.delete("/customs/invoices/{invoice_id}")
def remove_invoice(invoice_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsInvoice, invoice_id, user.session_company_id)
    ensure_version(row, version)
    customs.delete_invoice(db, user, user.session_company_id, row)
    return ok({"ok": True})


@router.post("/customs/invoices/batch-delete")
def batch_invoices(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    count = _batch(db, user, user.session_company_id, CustomsInvoice, payload.get("items") or [], customs.delete_invoice)
    return ok({"count": count})


@router.get("/customs/invoices/{invoice_id}/export")
def export_invoice(invoice_id: int, template_id: int | None = None, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsInvoice, invoice_id, user.session_company_id)
    company = db.get(Company, user.session_company_id)
    content, filename = build_form(db, company, "customs_invoice", row.id, template_id)
    customs.mark_exported(db, user, row)
    return _file(content, filename, media_type_for(filename))


@router.get("/customs/invoices/{invoice_id}/zip")
def zip_invoice(invoice_id: int, template_id: int | None = None, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsInvoice, invoice_id, user.session_company_id)
    content = customs_xlsx.invoice_zip(db, row, template_id)
    customs.mark_exported(db, user, row)
    return _file(content, f"{row.invoice_no}-报关文件.zip", ZIP)


@router.post("/customs/clearances")
def create_clearance(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = customs.generate_clearance(db, user, user.session_company_id, payload)
    return ok(customs.clearance_view(db, row))


@router.post("/customs/clearances/preview")
def preview_clearance(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    return ok(customs.preview_clearance(db, user, user.session_company_id, payload))


@router.get("/customs/clearances")
def list_clearances(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = customs.list_clearances(db, user.session_company_id, _params(request))
    items, total, page_no, size = customs._page(rows, _params(request))
    return page(items, total, page_no, size)


@router.get("/customs/clearances/{clearance_id}")
def get_clearance(clearance_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsClearance, clearance_id, user.session_company_id)
    return ok(customs.clearance_view(db, row))


@router.put("/customs/clearances/{clearance_id}")
def update_clearance(clearance_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsClearance, clearance_id, user.session_company_id)
    customs.save_clearance(db, user, user.session_company_id, row, payload)
    return ok(customs.clearance_view(db, row))


@router.delete("/customs/clearances/{clearance_id}")
def remove_clearance(clearance_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsClearance, clearance_id, user.session_company_id)
    ensure_version(row, version)
    customs.delete_clearance(db, user, user.session_company_id, row)
    return ok({"ok": True})


@router.post("/customs/clearances/batch-delete")
def batch_clearances(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    count = _batch(db, user, user.session_company_id, CustomsClearance, payload.get("items") or [], customs.delete_clearance)
    return ok({"count": count})


@router.get("/customs/clearances/{clearance_id}/export")
def export_clearance(clearance_id: int, template_id: int | None = None, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsClearance, clearance_id, user.session_company_id)
    company = db.get(Company, user.session_company_id)
    content, filename = build_form(db, company, "customs_clearance", row.id, template_id)
    customs.mark_exported(db, user, row)
    return _file(content, filename, media_type_for(filename))


@router.get("/customs/clearances/{clearance_id}/zip")
def zip_clearance(clearance_id: int, template_id: int | None = None, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsClearance, clearance_id, user.session_company_id)
    content = customs_xlsx.clearance_zip(db, row, template_id)
    customs.mark_exported(db, user, row)
    return _file(content, f"{row.invoice_no or '清关发票'}-清关文件.zip", ZIP)


@router.post("/customs/elements")
def create_element(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = customs.generate_element(db, user, user.session_company_id, payload)
    return ok(customs.element_view(db, row))


@router.post("/customs/elements/preview")
def preview_element(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    return ok(customs.preview_element(db, user, user.session_company_id, payload))


@router.get("/customs/elements")
def list_elements(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = customs.list_elements(db, user.session_company_id, _params(request))
    items, total, page_no, size = customs._page(rows, _params(request))
    return page(items, total, page_no, size)


@router.get("/customs/elements/{element_id}")
def get_element(element_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsElement, element_id, user.session_company_id)
    return ok(customs.element_view(db, row))


@router.put("/customs/elements/{element_id}")
def update_element(element_id: int, payload: dict, request: Request, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsElement, element_id, user.session_company_id)
    confirm = bool(payload.get("confirm") or request.query_params.get("confirm") == "1")
    issues = customs.save_element_items(db, user, user.session_company_id, row, payload, confirm=confirm)
    data = customs.element_view(db, row)
    data["issues"] = issues
    return ok(data)


@router.delete("/customs/elements/{element_id}")
def remove_element(element_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, CustomsElement, element_id, user.session_company_id)
    ensure_version(row, version)
    customs.delete_element(db, user, user.session_company_id, row)
    return ok({"ok": True})


@router.post("/customs/elements/batch-delete")
def batch_elements(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    count = _batch(db, user, user.session_company_id, CustomsElement, payload.get("items") or [], customs.delete_element)
    return ok({"count": count})


@router.get("/customs/hs")
def list_hs(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = customs.list_hs(db, user.session_company_id, _params(request))
    items, total, page_no, size = customs._page(rows, _params(request))
    return page(items, total, page_no, size)


@router.post("/customs/hs")
def create_hs(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = customs.save_hs(db, user, user.session_company_id, payload, None)
    return ok({"id": row.id})


@router.put("/customs/hs/{hs_id}")
def update_hs(hs_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, HsCodeLibrary, hs_id, user.session_company_id)
    customs.save_hs(db, user, user.session_company_id, payload, row)
    return ok({"id": row.id})


@router.delete("/customs/hs/{hs_id}")
def remove_hs(hs_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    from ..services.util import ensure_creator, soft_delete, op_log

    row = get_row(db, HsCodeLibrary, hs_id, user.session_company_id)
    ensure_version(row, version)
    ensure_creator(row, user)
    soft_delete(row, user.employee_id)
    op_log(db, user, user.session_company_id, "删除", "hs_code_library", row.hs_code, {})
    return ok({"ok": True})


@router.post("/customs/hs/batch-delete")
def batch_hs(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    from ..services.util import ensure_creator, soft_delete

    def deleter(db, user, company_id, row):
        ensure_creator(row, user)
        soft_delete(row, user.employee_id)

    count = _batch(db, user, user.session_company_id, HsCodeLibrary, payload.get("items") or [], deleter)
    return ok({"count": count})


@router.get("/customs/hs/match")
def match_hs(name: str = "", user=Depends(current_user), db=Depends(get_db)):
    return ok(customs.match_hs(db, user.session_company_id, name))


@router.get("/customs/rates")
def list_rates(request: Request, user=Depends(current_user), db=Depends(get_db)):
    rows = customs.list_rates(db, user.session_company_id, _params(request))
    items, total, page_no, size = customs._page(rows, _params(request))
    return page(items, total, page_no, size)


@router.post("/customs/rates")
def create_rate(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = customs.save_rate(db, user, user.session_company_id, payload, None)
    return ok({"id": row.id})


@router.put("/customs/rates/{rate_id}")
def update_rate(rate_id: int, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, ExchangeRate, rate_id, user.session_company_id)
    customs.save_rate(db, user, user.session_company_id, payload, row)
    return ok({"id": row.id})


@router.delete("/customs/rates/{rate_id}")
def remove_rate(rate_id: int, version: int, user=Depends(current_user), db=Depends(get_db)):
    from ..services.util import ensure_creator, soft_delete

    row = get_row(db, ExchangeRate, rate_id, user.session_company_id)
    ensure_version(row, version)
    ensure_creator(row, user)
    soft_delete(row, user.employee_id)
    return ok({"ok": True})


@router.post("/customs/rates/batch-delete")
def batch_rates(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    from ..services.util import ensure_creator, soft_delete

    def deleter(db, user, company_id, row):
        ensure_creator(row, user)
        soft_delete(row, user.employee_id)

    count = _batch(db, user, user.session_company_id, ExchangeRate, payload.get("items") or [], deleter)
    return ok({"count": count})


@router.get("/settings/deepseek")
def get_deepseek(user=Depends(current_user), db=Depends(get_db)):
    row = customs.deepseek_row(db, user.session_company_id, user)
    return ok(customs.deepseek_view(row))


@router.put("/settings/deepseek")
def put_deepseek(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    row = customs.save_deepseek(db, user, user.session_company_id, payload)
    return ok(customs.deepseek_view(row))


@router.post("/settings/deepseek/test")
def test_deepseek(payload: dict, user=Depends(current_user)):
    _ = user
    return ok(customs.probe_deepseek(payload))


@router.post("/ai/customs/check")
def ai_check(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    from ..services.util import op_log

    result = customs.ai_check(db, user.session_company_id, payload)
    logged = {key: value for key, value in result.items() if key != "api_key"}
    op_log(db, user, user.session_company_id, "AI检查", "customs_ai", payload.get("hsCode") or payload.get("hs_code") or "", logged)
    return ok(result)


@router.get("/files")
def list_files(business_type: str = "", business_id: int | None = None, user=Depends(current_user), db=Depends(get_db)):
    return ok(customs.list_files(db, user.session_company_id, business_type, business_id))


@router.post("/files")
async def upload_file(
    business_type: str = Form(...),
    business_id: int = Form(...),
    file: UploadFile = File(...),
    user=Depends(current_user),
    db=Depends(get_db),
):
    content = await file.read()
    row = customs.save_file(db, user, user.session_company_id, business_type, business_id, file.filename or "file", content)
    return ok({"id": row.id, "file_name": row.file_name})


@router.delete("/files/{file_id}")
def remove_file(file_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, BizFile, file_id, user.session_company_id)
    customs.remove_file(db, user, user.session_company_id, row)
    return ok({"ok": True})


@router.get("/files/{file_id}/download")
def download_file(file_id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_row(db, BizFile, file_id, user.session_company_id)
    path = Path(row.file_path)
    if not path.is_file():
        raise BizError("文件不存在")
    return FileResponse(path, filename=row.file_name)
