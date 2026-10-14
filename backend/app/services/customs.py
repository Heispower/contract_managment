"""报关数据链：入仓 → 库存 → 报关物料 → 发票 / 清关 / 要素。原始物料只录一次。"""
import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path
from urllib import request as urlrequest

from ..config import UPLOAD_DIR
from ..errors import BizError
from ..models import (
    BizFile,
    CustomsClearance,
    CustomsClearanceItem,
    CustomsClearancePl,
    CustomsElement,
    CustomsElementItem,
    CustomsElementLine,
    CustomsInvoice,
    CustomsInvoiceItem,
    CustomsInvoiceLink,
    Contract,
    ContractItem,
    CustomsMaterial,
    CustomsStock,
    DeepseekSetting,
    ExchangeRate,
    HsCodeLibrary,
    Party,
    PurchasePlan,
    Warehouse,
    WarehouseReceipt,
    WarehouseReceiptItem,
    WmsBill,
    WmsItem,
    now,
)
from ..money import D, ZERO, line_total, money_str, qty_str, round2
from .present import dump
from .util import (
    bump,
    ensure_code_free,
    ensure_creator,
    ensure_version,
    get_row,
    next_daily_code,
    op_log,
    parse_date,
    q,
    soft_delete,
    stamp_new,
)

REQUIRED = (
    ("contract_no", "合同号"),
    ("packing_list_no", "箱单号"),
    ("material_category", "物料大类"),
    ("material_code", "物料编号"),
    ("material_name", "物料名称"),
    ("origin_country", "产地"),
    ("equipment", "使用设备"),
    ("gross_weight", "毛重"),
    ("net_weight", "净重"),
    ("volume", "体积"),
)
ASSIGN_FIELDS = {
    "material_category": "物料大类",
    "container_no": "集装箱号",
    "bill_no": "提单号",
    "vessel_voyage": "船名/航号",
    "packing_list_no": "箱单号",
    "origin_country": "产地",
    "equipment": "使用设备",
    "port_of_shipment": "出发港",
    "port_of_destination": "目的港",
    "consignee": "收货人",
    "payment_terms": "付款条款",
    "hs_code": "HS Code",
    "declaration_elements": "申报要素",
    "receipt_no": "入仓单号",
    "remark": "备注",
    "special_declare": "特殊申报",
}
CAMEL = {
    "receiptNo": "receipt_no",
    "receiptDate": "receipt_date",
    "supplierId": "supplier_id",
    "contractNo": "contract_no",
    "packingListNo": "packing_list_no",
    "materialCode": "material_code",
    "materialName": "material_name",
    "materialNameEn": "material_name_en",
    "materialCategory": "material_category",
    "boxNo": "box_no",
    "containerNo": "container_no",
    "billNo": "bill_no",
    "vesselName": "vessel_name",
    "voyageNo": "voyage_no",
    "vesselVoyage": "vessel_voyage",
    "grossWeight": "gross_weight",
    "netWeight": "net_weight",
    "originCountry": "origin_country",
    "poNo": "po_no",
    "specialDeclare": "special_declare",
}


def _snake(payload: dict) -> dict:
    out = {}
    for key, value in (payload or {}).items():
        out[CAMEL.get(key, key)] = value
    return out


def _text(value):
    return str(value or "").strip()


def _hide_generated(params, key):
    return _text(params.get(key)).lower() in ("1", "true", "是", "yes")


def _vessel_voyage(name=None, no=None, row=None):
    if row is not None:
        name = getattr(row, "vessel_name", None)
        no = getattr(row, "voyage_no", None)
    name = _text(name)
    no = _text(no)
    if name and no:
        return f"{name}/{no}"
    return name or no


def _split_vessel_voyage(value):
    text = _text(value)
    if not text:
        return "", ""
    if "/" in text:
        name, no = text.split("/", 1)
        return name.strip(), no.strip()
    return text, ""


def _qty(value):
    if value in (None, ""):
        return None
    return D(value)


def _bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip() in ("1", "true", "True", "是", "特殊申报")


def _size(row):
    parts = [qty_str(getattr(row, key)) for key in ("length", "width", "height") if getattr(row, key, None) not in (None, "")]
    return "×".join(parts) if parts else ""


def _star_size(row):
    """尺寸只拼成长*宽*高，缺任一维就显示 -，不计算体积。"""
    parts = []
    for key in ("length", "width", "height"):
        raw = getattr(row, key, None)
        if raw in (None, ""):
            return "-"
        parts.append(qty_str(raw))
    return "*".join(parts)


def _group_size(rows):
    for row in rows:
        text = _star_size(row)
        if text != "-":
            return text
    return "-"


def _sum_optional(rows, key):
    total = ZERO
    found = False
    for row in rows:
        raw = getattr(row, key, None)
        if raw in (None, ""):
            continue
        found = True
        total += D(raw)
    return total if found else None


def _join_unique(values):
    seen = []
    for value in values:
        text = _text(value)
        if text and text not in seen:
            seen.append(text)
    return ", ".join(seen)


def _first_weekday(when: date) -> date:
    day = when.replace(day=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _rate_label(when: date) -> str:
    day = _first_weekday(when)
    return f"{day.year}年{day.month}月{day.day}日汇率"


DEFAULT_PORT_FROM = "SHANGHAI, CHINA"
DEFAULT_PORT_TO = "GEORGETOWN, GUYANA"
DEFAULT_TERMS = "Payment against Commercial invoice within 3 months after arrival of goods, by T/T"
DEFAULT_CONSIGNEE = "Bosai Minerals Group (Guyana) Inc."


def _packages(rows):
    boxes = {(_text(row.box_no) or f"#{row.id}") for row in rows}
    return len(boxes)


def _copy_fields(src, dst, extra=None):
    keys = (
        "material_category", "material_code", "material_name", "material_name_en", "specification",
        "unit", "quantity", "origin_country", "equipment", "box_no", "container_no", "bill_no",
        "vessel_name", "voyage_no", "gross_weight", "net_weight", "length", "width", "height",
        "volume", "po_no", "price", "package_count", "inquiry_name", "inquiry_model", "inquiry_qty",
        "port_of_shipment", "port_of_destination", "consignee", "payment_terms", "hs_code", "declaration_elements", "remark",
        "special_declare",
    )
    for key in keys:
        setattr(dst, key, getattr(src, key))
    if extra:
        for key, value in extra.items():
            setattr(dst, key, value)


def _item_view(row, extra=None):
    data = {
        "id": row.id,
        "version": getattr(row, "version", None),
        "receipt_id": getattr(row, "receipt_id", None),
        "receipt_item_id": getattr(row, "receipt_item_id", getattr(row, "id", None)),
        "receipt_no": getattr(row, "receipt_no", "") or "",
        "wms_bill_id": getattr(row, "wms_bill_id", None),
        "wms_item_id": getattr(row, "wms_item_id", None),
        "contract_no": getattr(row, "contract_no", "") or "",
        "packing_list_no": getattr(row, "packing_list_no", "") or "",
        "material_category": row.material_category or "",
        "material_code": row.material_code,
        "material_name": row.material_name or "",
        "material_name_en": row.material_name_en or "",
        "specification": row.specification or "",
        "unit": row.unit or "",
        "quantity": qty_str(row.quantity),
        "origin_country": row.origin_country or "",
        "equipment": row.equipment or "",
        "box_no": row.box_no or "",
        "container_no": row.container_no or "",
        "bill_no": row.bill_no or "",
        "vessel_name": row.vessel_name or "",
        "voyage_no": row.voyage_no or "",
        "vessel_voyage": _vessel_voyage(row=row),
        "gross_weight": qty_str(row.gross_weight) if row.gross_weight is not None else "",
        "net_weight": qty_str(row.net_weight) if row.net_weight is not None else "",
        "length": qty_str(row.length) if row.length is not None else "",
        "width": qty_str(row.width) if row.width is not None else "",
        "height": qty_str(row.height) if row.height is not None else "",
        "volume": qty_str(row.volume) if row.volume is not None else "",
        "size_text": _size(row),
        "po_no": row.po_no or "",
        "price": money_str(row.price),
        "package_count": row.package_count if getattr(row, "package_count", None) is not None else "",
        "inquiry_name": getattr(row, "inquiry_name", "") or "",
        "inquiry_model": getattr(row, "inquiry_model", "") or "",
        "inquiry_qty": qty_str(row.inquiry_qty) if getattr(row, "inquiry_qty", None) is not None else "",
        "port_of_shipment": getattr(row, "port_of_shipment", "") or "",
        "port_of_destination": getattr(row, "port_of_destination", "") or "",
        "consignee": getattr(row, "consignee", "") or "",
        "payment_terms": getattr(row, "payment_terms", "") or "",
        "hs_code": getattr(row, "hs_code", "") or "",
        "declaration_elements": getattr(row, "declaration_elements", "") or "",
        "remark": getattr(row, "remark", "") or "",
        "special_declare": bool(row.special_declare),
        "special_label": "特殊申报" if row.special_declare else "普通",
    }
    if extra:
        data.update(extra)
    return data


def _fill_item(row, payload):
    data = _snake(payload)
    code = _text(data.get("material_code"))
    if not code:
        raise BizError("物料编号不能为空")
    qty = D(data.get("quantity") or 0)
    if qty <= 0:
        raise BizError("数量必须大于 0")
    row.material_category = _text(data.get("material_category"))
    row.material_code = code
    row.material_name = _text(data.get("material_name"))
    row.material_name_en = _text(data.get("material_name_en"))
    row.specification = _text(data.get("specification") or data.get("spec"))
    row.unit = _text(data.get("unit"))
    row.quantity = qty
    row.origin_country = _text(data.get("origin_country"))
    row.equipment = _text(data.get("equipment"))
    row.box_no = _text(data.get("box_no"))
    row.container_no = _text(data.get("container_no"))
    row.bill_no = _text(data.get("bill_no"))
    if _text(data.get("vessel_voyage")) or "vessel_voyage" in data:
        name, no = _split_vessel_voyage(data.get("vessel_voyage"))
        data["vessel_name"] = name
        data["voyage_no"] = no
    row.vessel_name = _text(data.get("vessel_name"))
    row.voyage_no = _text(data.get("voyage_no"))
    row.gross_weight = _qty(data.get("gross_weight"))
    row.net_weight = _qty(data.get("net_weight"))
    row.length = _qty(data.get("length"))
    row.width = _qty(data.get("width"))
    row.height = _qty(data.get("height"))
    row.volume = _qty(data.get("volume"))
    row.po_no = _text(data.get("po_no"))
    row.price = D(data.get("price") or 0)
    raw_packages = data.get("package_count")
    row.package_count = int(D(raw_packages)) if raw_packages not in (None, "") else None
    row.inquiry_name = _text(data.get("inquiry_name"))
    row.inquiry_model = _text(data.get("inquiry_model"))
    row.inquiry_qty = _qty(data.get("inquiry_qty"))
    row.port_of_shipment = _text(data.get("port_of_shipment"))
    row.port_of_destination = _text(data.get("port_of_destination"))
    row.consignee = _text(data.get("consignee"))
    row.payment_terms = _text(data.get("payment_terms"))
    row.hs_code = _text(data.get("hs_code"))
    row.declaration_elements = _text(data.get("declaration_elements"))
    row.remark = _text(data.get("remark"))
    row.special_declare = _bool(data.get("special_declare"))


def _sync_downstream(db, user, company_id, receipt, item):
    extra = {
        "receipt_id": receipt.id,
        "receipt_item_id": item.id,
        "receipt_no": receipt.receipt_no,
        "contract_no": receipt.contract_no or "",
        "packing_list_no": receipt.packing_list_no or "",
    }
    stock = db.query(CustomsStock).filter(CustomsStock.company_id == company_id, CustomsStock.receipt_item_id == item.id, CustomsStock.deleted_at.is_(None)).first()
    if stock is None:
        stock = CustomsStock()
        stamp_new(stock, user, company_id)
        db.add(stock)
    _copy_fields(item, stock, extra)
    material = db.query(CustomsMaterial).filter(CustomsMaterial.company_id == company_id, CustomsMaterial.receipt_item_id == item.id, CustomsMaterial.deleted_at.is_(None)).first()
    if material is None:
        material = CustomsMaterial(status="正常")
        stamp_new(material, user, company_id)
        db.add(material)
    keep = {"invoice_id": material.invoice_id, "clearance_id": material.clearance_id, "element_id": material.element_id, "status": material.status or "正常"}
    _copy_fields(item, material, extra)
    for key, value in keep.items():
        setattr(material, key, value)
    bump(stock, user.employee_id)
    bump(material, user.employee_id)


def sync_from_wms(db, user, company_id, bill):
    """采购入库保存后写入报关物料。入仓单号与入库单号不是同一字段，这里不写入。"""
    if getattr(bill, "type", None) != "inbound":
        return
    contract = db.get(Contract, bill.contract_id)
    items = db.query(WmsItem).filter(WmsItem.bill_id == bill.id, WmsItem.deleted_at.is_(None)).all()
    keep = set()
    for item in items:
        keep.add(item.id)
        material = db.query(CustomsMaterial).filter(
            CustomsMaterial.company_id == company_id,
            CustomsMaterial.wms_item_id == item.id,
            CustomsMaterial.deleted_at.is_(None),
        ).first()
        if material is None:
            material = CustomsMaterial(
                status="正常",
                receipt_id=0,
                receipt_item_id=-item.id,
                wms_bill_id=bill.id,
                wms_item_id=item.id,
            )
            stamp_new(material, user, company_id)
            db.add(material)
        src = None
        if contract:
            src = db.query(ContractItem).filter(
                ContractItem.contract_id == contract.id,
                ContractItem.material_code == item.material_code,
                ContractItem.deleted_at.is_(None),
            ).first()
        material.wms_bill_id = bill.id
        material.wms_item_id = item.id
        if _text(material.receipt_no) == _text(bill.bill_code):
            material.receipt_no = ""
        material.contract_no = (contract.contract_code if contract else "") or material.contract_no or ""
        material.material_code = item.material_code
        material.material_name = item.name_cn or (src.name_cn if src else "") or material.material_name or ""
        if src and src.name_en:
            material.material_name_en = src.name_en
        material.specification = item.spec or (src.spec if src else "") or material.specification or ""
        material.unit = item.unit or (src.unit if src else "") or material.unit or ""
        material.quantity = item.qty
        material.price = item.price
        material.equipment = item.category or (getattr(src, "category", None) if src else "") or material.equipment or ""
        bump(material, user.employee_id)
        db.flush()
    leftovers = db.query(CustomsMaterial).filter(
        CustomsMaterial.company_id == company_id,
        CustomsMaterial.wms_bill_id == bill.id,
        CustomsMaterial.deleted_at.is_(None),
    ).all()
    for material in leftovers:
        if material.wms_item_id in keep:
            continue
        if material.invoice_id or material.clearance_id or material.element_id:
            raise BizError("该物料已经被报关发票/报关要素引用，请先解除关联。")
        soft_delete(material, user.employee_id)


def unlink_wms(db, user, company_id, bill):
    rows = db.query(CustomsMaterial).filter(
        CustomsMaterial.company_id == company_id,
        CustomsMaterial.wms_bill_id == bill.id,
        CustomsMaterial.deleted_at.is_(None),
    ).all()
    for row in rows:
        if row.invoice_id or row.clearance_id or row.element_id:
            raise BizError("该物料已经被报关发票/报关要素引用，请先解除关联。")
    for row in rows:
        soft_delete(row, user.employee_id)


def material_chain(db, row: CustomsMaterial):
    """详情上展示：采购合同 → 采购入库 → 报关发票 → 清关发票。"""
    bill = db.get(WmsBill, row.wms_bill_id) if row.wms_bill_id else None
    contract = db.get(Contract, bill.contract_id) if bill and bill.contract_id else None
    invoice = db.get(CustomsInvoice, row.invoice_id) if row.invoice_id else None
    clearance = db.get(CustomsClearance, row.clearance_id) if row.clearance_id else None
    return {
        "contract_id": contract.id if contract else None,
        "contract_code": contract.contract_code if contract else "",
        "contract_name": contract.name if contract else "",
        "inbound_id": bill.id if bill else None,
        "inbound_code": bill.bill_code if bill else "",
        "customs_invoice_no": invoice.invoice_no if invoice else "",
        "clearance_invoice_no": (clearance.invoice_no or "无发票号") if clearance else "",
    }


def repair_orphan_chain(db):
    """没有采购入库的报关物料，补上对应的采购合同和采购入库。"""
    from .calc import recalc_stock
    from .ops import save_contract
    from .seed import SeedUser

    orphans = db.query(CustomsMaterial).filter(
        CustomsMaterial.deleted_at.is_(None),
        CustomsMaterial.wms_bill_id.is_(None),
    ).all()
    if not orphans:
        return
    user = SeedUser("admin")
    grouped = {}
    for row in orphans:
        grouped.setdefault(row.company_id, []).append(row)
    for company_id, rows in grouped.items():
        warehouse = db.query(Warehouse).filter(
            Warehouse.company_id == company_id,
            Warehouse.deleted_at.is_(None),
            Warehouse.status == "启用",
        ).first()
        if warehouse is None:
            continue
        receipt_ids = {row.receipt_id for row in rows if row.receipt_id}
        receipts = {}
        if receipt_ids:
            for rec in db.query(WarehouseReceipt).filter(WarehouseReceipt.id.in_(receipt_ids)).all():
                receipts[rec.id] = rec
        by_contract = {}
        for row in rows:
            rec = receipts.get(row.receipt_id)
            code = _text(row.contract_no) or _text(getattr(rec, "contract_no", "")) or f"CG-{row.receipt_no or row.id}"
            by_contract.setdefault(code, []).append((row, rec))
        contracts = {}
        for code, members in by_contract.items():
            contract = db.query(Contract).filter(
                Contract.company_id == company_id,
                Contract.contract_code == code,
                Contract.deleted_at.is_(None),
            ).first()
            if contract and contract.direction != "purchase":
                continue
            if contract is None:
                rec = next((item[1] for item in members if item[1] is not None), None)
                supplier_id = getattr(rec, "supplier_id", None)
                if not supplier_id:
                    party = db.query(Party).filter(
                        Party.company_id == company_id,
                        Party.type == "supplier",
                        Party.deleted_at.is_(None),
                    ).first()
                    supplier_id = party.id if party else None
                if not supplier_id:
                    continue
                merged = {}
                for row, _rec in members:
                    slot = merged.setdefault(row.material_code, {
                        "qty": ZERO, "price": D(row.price), "name": row.material_name or row.material_code,
                        "spec": row.specification or "", "unit": row.unit or "",
                        "category": row.equipment or row.material_category or "",
                    })
                    slot["qty"] += D(row.quantity)
                sign = dump(getattr(rec, "receipt_date", None)) or date.today().isoformat()
                for key, val in merged.items():
                    plan = db.query(PurchasePlan).filter(
                        PurchasePlan.company_id == company_id,
                        PurchasePlan.material_code == key,
                        PurchasePlan.deleted_at.is_(None),
                    ).first()
                    if plan is None:
                        plan = PurchasePlan(
                            plan_month=sign[:7],
                            material_code=key,
                            name_cn=val["name"],
                            spec=val["spec"],
                            unit=val["unit"],
                            qty=val["qty"],
                            purpose="报关补链",
                        )
                        stamp_new(plan, user, company_id)
                        db.add(plan)
                    elif D(plan.qty) < val["qty"]:
                        plan.qty = val["qty"]
                db.flush()
                contract = save_contract(db, user, company_id, {
                    "contract_code": code,
                    "name": f"{code}采购合同",
                    "direction": "purchase",
                    "nature": "main",
                    "type_name": "材料采购",
                    "party_id": supplier_id,
                    "owner_id": "admin",
                    "status": "已签订",
                    "pricing": "fixed",
                    "tax_rate": "13",
                    "sign_date": sign,
                    "content": "补齐报关物料所依赖的采购合同",
                    "items": [{
                        "material_code": key,
                        "name_cn": val["name"],
                        "spec": val["spec"],
                        "unit": val["unit"],
                        "qty": qty_str(val["qty"]),
                        "price": money_str(val["price"]),
                        "category": val["category"],
                    } for key, val in merged.items()],
                })
            contracts[code] = contract
        by_receipt = {}
        for row in rows:
            by_receipt.setdefault(row.receipt_id or -row.id, []).append(row)
        touched = set()
        for receipt_key, members in by_receipt.items():
            rec = receipts.get(receipt_key)
            code = _text(members[0].contract_no) or _text(getattr(rec, "contract_no", "")) or f"CG-{members[0].receipt_no or members[0].id}"
            contract = contracts.get(code)
            if contract is None:
                continue
            bill_code = (rec.receipt_no if rec else "") or members[0].receipt_no or f"RK-{receipt_key}"
            bill = db.query(WmsBill).filter(
                WmsBill.company_id == company_id,
                WmsBill.bill_code == bill_code,
                WmsBill.deleted_at.is_(None),
            ).first()
            if bill is None:
                bill = WmsBill(
                    type="inbound",
                    bill_code=bill_code,
                    bill_date=getattr(rec, "receipt_date", None) or date.today(),
                    contract_id=contract.id,
                    party_id=contract.party_id,
                    party_name=contract.party_name or "",
                    warehouse_id=warehouse.id,
                    remark=getattr(rec, "remark", "") or "",
                )
                stamp_new(bill, user, company_id)
                db.add(bill)
                db.flush()
            existing_items = {
                item.material_code: item
                for item in db.query(WmsItem).filter(WmsItem.bill_id == bill.id, WmsItem.deleted_at.is_(None)).all()
            }
            for row in members:
                item = existing_items.get(row.material_code)
                if item is None:
                    item = WmsItem(
                        bill_id=bill.id,
                        material_code=row.material_code,
                        name_cn=row.material_name or "",
                        spec=row.specification or "",
                        unit=row.unit or "",
                        qty=row.quantity,
                        price=row.price or ZERO,
                        amount=line_total(row.quantity, row.price or ZERO),
                        category=row.equipment or "",
                    )
                    stamp_new(item, user, company_id)
                    db.add(item)
                    db.flush()
                    existing_items[row.material_code] = item
                else:
                    item.qty = D(item.qty) + D(row.quantity)
                    item.amount = line_total(item.qty, item.price)
                row.wms_bill_id = bill.id
                row.wms_item_id = item.id
                row.contract_no = contract.contract_code
                touched.add((warehouse.id, row.material_code))
        for warehouse_id, material_code in touched:
            recalc_stock(db, company_id, warehouse_id, material_code)
    db.flush()


def backfill_from_wms(db):
    class _Actor:
        employee_id = "system"

    bills = db.query(WmsBill).filter(WmsBill.type == "inbound", WmsBill.deleted_at.is_(None)).all()
    for bill in bills:
        actor = _Actor()
        actor.employee_id = bill.created_by or "system"
        sync_from_wms(db, actor, bill.company_id, bill)


def _receipt_view(db, row: WarehouseReceipt):
    items = q(db, WarehouseReceiptItem, row.company_id).filter(WarehouseReceiptItem.receipt_id == row.id).order_by(WarehouseReceiptItem.id).all()
    return {
        "id": row.id,
        "version": row.version,
        "receipt_no": row.receipt_no,
        "receipt_date": dump(row.receipt_date),
        "supplier_id": row.supplier_id,
        "supplier_name": row.supplier_name or "",
        "contract_no": row.contract_no or "",
        "packing_list_no": row.packing_list_no or "",
        "remark": row.remark or "",
        "status": row.status,
        "qty_total": qty_str(sum((D(item.quantity) for item in items), ZERO)),
        "item_count": len(items),
        "created_by": row.created_by,
        "items": [_item_view(item, {"receipt_no": row.receipt_no, "contract_no": row.contract_no or "", "packing_list_no": row.packing_list_no or ""}) for item in items],
    }


def list_receipts(db, company_id, params):
    query = q(db, WarehouseReceipt, company_id)
    keyword = _text(params.get("keyword"))
    contract_no = _text(params.get("contract_no"))
    packing = _text(params.get("packing_list_no"))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter((WarehouseReceipt.receipt_no.like(like)) | (WarehouseReceipt.contract_no.like(like)))
    if contract_no:
        query = query.filter(WarehouseReceipt.contract_no == contract_no)
    if packing:
        query = query.filter(WarehouseReceipt.packing_list_no == packing)
    rows = query.order_by(WarehouseReceipt.id.desc()).all()
    items = []
    for row in rows:
        data = _receipt_view(db, row)
        data.pop("items", None)
        items.append(data)
    return items


CHAIN_BLOCK = "报关物料只能来自采购入库。请先签订采购合同，再办理采购入库，然后才能生成报关发票、清关发票和报关要素。"


def save_receipt(db, user, company_id, payload, row):
    raise BizError(CHAIN_BLOCK)
    data = _snake(payload)
    code = _text(data.get("receipt_no")) or next_daily_code(db, WarehouseReceipt, company_id, WarehouseReceipt.receipt_no, "RK")
    if row:
        ensure_creator(row, user)
        ensure_version(row, data.get("version"))
        if code != row.receipt_no:
            ensure_code_free(db, WarehouseReceipt, company_id, WarehouseReceipt.receipt_no, code, row.id)
        bump(row, user.employee_id)
    else:
        ensure_code_free(db, WarehouseReceipt, company_id, WarehouseReceipt.receipt_no, code)
        row = WarehouseReceipt()
        stamp_new(row, user, company_id)
        db.add(row)
    row.receipt_no = code
    row.receipt_date = parse_date(data.get("receipt_date")) or date.today()
    row.supplier_id = int(data["supplier_id"]) if data.get("supplier_id") else None
    if row.supplier_id:
        party = get_row(db, Party, row.supplier_id, company_id)
        row.supplier_name = party.name
    else:
        row.supplier_name = _text(data.get("supplier_name"))
    row.contract_no = _text(data.get("contract_no"))
    row.packing_list_no = _text(data.get("packing_list_no"))
    row.remark = _text(data.get("remark"))
    row.status = data.get("status") or "已生成"
    items = data.get("items") or []
    if not items:
        raise BizError("请填写入仓明细")
    db.flush()
    existing = q(db, WarehouseReceiptItem, company_id).filter(WarehouseReceiptItem.receipt_id == row.id).all()
    keep = []
    for raw in items:
        item_id = raw.get("id")
        item = next((old for old in existing if item_id and old.id == int(item_id)), None)
        if item is None:
            item = WarehouseReceiptItem(receipt_id=row.id)
            stamp_new(item, user, company_id)
            db.add(item)
        else:
            bump(item, user.employee_id)
        _fill_item(item, raw)
        db.flush()
        _sync_downstream(db, user, company_id, row, item)
        keep.append(item.id)
    for old in existing:
        if old.id in keep:
            continue
        material = db.query(CustomsMaterial).filter(CustomsMaterial.receipt_item_id == old.id, CustomsMaterial.deleted_at.is_(None)).first()
        if material and (material.invoice_id or material.clearance_id or material.element_id):
            raise BizError("该物料已经被报关发票/报关要素引用，请先解除关联。")
        for model in (CustomsStock, CustomsMaterial):
            hit = db.query(model).filter(model.receipt_item_id == old.id, model.deleted_at.is_(None)).first()
            if hit:
                soft_delete(hit, user.employee_id)
        soft_delete(old, user.employee_id)
    op_log(db, user, company_id, "修改" if payload.get("version") else "新增", "warehouse_receipt", row.receipt_no, {"items": len(keep)})
    db.flush()
    return row


def delete_receipt(db, user, company_id, row):
    ensure_creator(row, user)
    items = q(db, WarehouseReceiptItem, company_id).filter(WarehouseReceiptItem.receipt_id == row.id).all()
    for item in items:
        material = db.query(CustomsMaterial).filter(CustomsMaterial.receipt_item_id == item.id, CustomsMaterial.deleted_at.is_(None)).first()
        if material and (material.invoice_id or material.clearance_id or material.element_id):
            raise BizError("该物料已经被报关发票/报关要素引用，请先解除关联。")
    for item in items:
        for model in (CustomsStock, CustomsMaterial):
            hit = db.query(model).filter(model.receipt_item_id == item.id, model.deleted_at.is_(None)).first()
            if hit:
                soft_delete(hit, user.employee_id)
        soft_delete(item, user.employee_id)
    soft_delete(row, user.employee_id)
    op_log(db, user, company_id, "删除", "warehouse_receipt", row.receipt_no, {})


def import_receipt_api(db, user, company_id, payload):
    data = _snake(payload)
    items = data.get("items") or []
    if not items:
        raise BizError("明细不能为空")
    code = _text(data.get("receipt_no"))
    if code:
        taken = q(db, WarehouseReceipt, company_id).filter(WarehouseReceipt.receipt_no == code).first()
        if taken:
            raise BizError("入仓单号已存在")
    row = save_receipt(db, user, company_id, data, None)
    op_log(db, user, company_id, "API导入", "warehouse_receipt", row.receipt_no, {"items": len(items)})
    return _receipt_view(db, row)


def _filter_materials(db, company_id, params):
    query = q(db, CustomsMaterial, company_id)
    mapping = {
        "contract_no": CustomsMaterial.contract_no,
        "packing_list_no": CustomsMaterial.packing_list_no,
        "material_category": CustomsMaterial.material_category,
        "material_code": CustomsMaterial.material_code,
        "receipt_no": CustomsMaterial.receipt_no,
        "equipment": CustomsMaterial.equipment,
        "container_no": CustomsMaterial.container_no,
        "bill_no": CustomsMaterial.bill_no,
    }
    bill_id = _text(params.get("wms_bill_id"))
    if bill_id:
        query = query.filter(CustomsMaterial.wms_bill_id == int(bill_id))
    for key, column in mapping.items():
        value = _text(params.get(key))
        if value:
            query = query.filter(column == value)
    name = _text(params.get("material_name"))
    if name:
        query = query.filter(CustomsMaterial.material_name == name)
    voyage = _text(params.get("vessel_voyage") or params.get("vessel_name"))
    if voyage:
        from sqlalchemy import or_
        ship, no = _split_vessel_voyage(voyage)
        if ship and no:
            query = query.filter(CustomsMaterial.vessel_name == ship, CustomsMaterial.voyage_no == no)
        else:
            query = query.filter(or_(CustomsMaterial.vessel_name == voyage, CustomsMaterial.voyage_no == voyage))
    supplier = _text(params.get("supplier_name"))
    if supplier:
        from sqlalchemy import or_
        rec_ids = [row.id for row in q(db, WarehouseReceipt, company_id).filter(WarehouseReceipt.supplier_name == supplier).all()]
        bill_ids = [row.id for row in q(db, WmsBill, company_id).filter(WmsBill.party_name == supplier).all()]
        parts = []
        if rec_ids:
            parts.append(CustomsMaterial.receipt_id.in_(rec_ids))
        if bill_ids:
            parts.append(CustomsMaterial.wms_bill_id.in_(bill_ids))
        query = query.filter(or_(*parts)) if parts else query.filter(False)
    special = _text(params.get("special_declare"))
    if special in ("1", "true", "是", "特殊申报"):
        query = query.filter(CustomsMaterial.special_declare.is_(True))
    if special in ("0", "false", "否", "普通"):
        query = query.filter(CustomsMaterial.special_declare.is_(False))
    if _text(params.get("unlinked")) == "invoice" or _hide_generated(params, "hide_invoice"):
        query = query.filter(CustomsMaterial.invoice_id.is_(None))
    if _text(params.get("unlinked")) == "clearance" or _hide_generated(params, "hide_clearance"):
        query = query.filter(CustomsMaterial.clearance_id.is_(None))
    if _hide_generated(params, "hide_element"):
        query = query.filter(CustomsMaterial.element_id.is_(None))
    start = _text(params.get("date_from") or params.get("start_date"))
    end = _text(params.get("date_to") or params.get("end_date"))
    if start or end:
        from sqlalchemy import or_
        receipt_q = q(db, WarehouseReceipt, company_id)
        bill_q = q(db, WmsBill, company_id).filter(WmsBill.type == "inbound")
        if start:
            start_date = parse_date(start)
            receipt_q = receipt_q.filter(WarehouseReceipt.receipt_date >= start_date)
            bill_q = bill_q.filter(WmsBill.bill_date >= start_date)
        if end:
            end_date = parse_date(end)
            receipt_q = receipt_q.filter(WarehouseReceipt.receipt_date <= end_date)
            bill_q = bill_q.filter(WmsBill.bill_date <= end_date)
        receipt_ids = [row.id for row in receipt_q.all()]
        bill_ids = [row.id for row in bill_q.all()]
        parts = []
        if receipt_ids:
            parts.append(CustomsMaterial.receipt_id.in_(receipt_ids))
        if bill_ids:
            parts.append(CustomsMaterial.wms_bill_id.in_(bill_ids))
        query = query.filter(or_(*parts)) if parts else query.filter(False)
    return query.order_by(CustomsMaterial.id.desc()).all()


def _material_parents(db, rows):
    receipt_ids = {row.receipt_id for row in rows if getattr(row, "receipt_id", None)}
    bill_ids = {row.wms_bill_id for row in rows if getattr(row, "wms_bill_id", None)}
    receipts = {}
    if receipt_ids:
        receipts = {item.id: item for item in db.query(WarehouseReceipt).filter(WarehouseReceipt.id.in_(receipt_ids)).all()}
    bills = {}
    if bill_ids:
        bills = {item.id: item for item in db.query(WmsBill).filter(WmsBill.id.in_(bill_ids)).all()}
    extra = {}
    for row in rows:
        data = {"receipt_date": "", "supplier_name": ""}
        bill = bills.get(getattr(row, "wms_bill_id", None))
        rec = receipts.get(getattr(row, "receipt_id", None))
        if bill:
            data["receipt_date"] = dump(bill.bill_date)
            data["supplier_name"] = bill.party_name or ""
        elif rec:
            data["receipt_date"] = dump(rec.receipt_date)
            data["supplier_name"] = rec.supplier_name or ""
        extra[row.id] = data
    return extra


def list_materials(db, company_id, params):
    rows = _filter_materials(db, company_id, params)
    parents = _material_parents(db, rows)
    return [_material_view(row, parents.get(row.id)) for row in rows]


OPTION_KEYS = (
    "receipt_no", "supplier_name", "contract_no", "packing_list_no",
    "material_category", "material_code", "material_name", "equipment",
    "container_no", "bill_no", "vessel_voyage",
)


def material_filter_options(db, company_id, params=None):
    """每个下拉按其余已选条件收窄，只保留能同时出现的值。"""
    params = params or {}
    rows = q(db, CustomsMaterial, company_id).all()
    if _hide_generated(params, "hide_invoice"):
        rows = [row for row in rows if not row.invoice_id]
    if _hide_generated(params, "hide_clearance"):
        rows = [row for row in rows if not row.clearance_id]
    if _hide_generated(params, "hide_element"):
        rows = [row for row in rows if not row.element_id]
    parents = _material_parents(db, rows)
    records = []
    for row in rows:
        parent = parents.get(row.id) or {}
        records.append({
            "receipt_no": _text(row.receipt_no),
            "supplier_name": _text(parent.get("supplier_name")),
            "contract_no": _text(row.contract_no),
            "packing_list_no": _text(row.packing_list_no),
            "material_category": _text(row.material_category),
            "material_code": _text(row.material_code),
            "material_name": _text(row.material_name),
            "equipment": _text(row.equipment),
            "container_no": _text(row.container_no),
            "bill_no": _text(row.bill_no),
            "vessel_voyage": _vessel_voyage(row=row),
        })

    def related(ignore):
        chosen = {
            key: _text(params.get(key))
            for key in OPTION_KEYS
            if key != ignore and _text(params.get(key))
        }
        values = set()
        for record in records:
            if any(record.get(key) != value for key, value in chosen.items()):
                continue
            text = record.get(ignore) or ""
            if text:
                values.add(text)
        return sorted(values)

    return {key: related(key) for key in OPTION_KEYS}


def _doc_flags(row: CustomsMaterial):
    invoice = bool(row.invoice_id)
    clearance = bool(row.clearance_id)
    element = bool(row.element_id)
    return {
        "invoice_generated": "已生成" if invoice else "未生成",
        "clearance_generated": "已生成" if clearance else "未生成",
        "element_generated": "已生成" if element else "未生成",
        "customs_done": "已报关" if invoice and clearance and element else "未报关",
    }


def _material_view(row: CustomsMaterial, extra=None):
    errors = missing_fields(row)
    data = _item_view(row, {
        "invoice_id": row.invoice_id,
        "clearance_id": row.clearance_id,
        "element_id": row.element_id,
        **_doc_flags(row),
        "status": row.status,
        "special_declare": bool(row.special_declare),
        "missing": [item[1] for item in errors],
        "missing_text": "、".join(item[1] for item in errors),
        "ready": not errors,
        "created_by": row.created_by,
        "receipt_date": "",
        "supplier_name": "",
    })
    if extra:
        data.update(extra)
    return data


def missing_fields(row):
    errors = []
    for key, label in REQUIRED:
        value = getattr(row, key, None)
        if value in (None, "", 0):
            errors.append((key, label))
    if not _size(row):
        errors.append(("size", "尺寸"))
    return errors


def save_material(db, user, company_id, row, payload):
    ensure_creator(row, user)
    ensure_version(row, payload.get("version"))
    _fill_item(row, payload)
    if "special_declare" in payload or "specialDeclare" in payload:
        row.special_declare = _bool(_snake(payload).get("special_declare"))
    if "packing_list_no" in payload:
        row.packing_list_no = _text(payload.get("packing_list_no"))
    if "receipt_no" in payload or "receiptNo" in payload:
        row.receipt_no = _text(payload.get("receipt_no") if "receipt_no" in payload else payload.get("receiptNo"))
    errors = missing_fields(row)
    if errors:
        raise BizError("报关物料必填项不完整", data={"fields": [{"key": key, "label": label} for key, label in errors]})
    bump(row, user.employee_id)
    stock = db.query(CustomsStock).filter(CustomsStock.receipt_item_id == row.receipt_item_id, CustomsStock.deleted_at.is_(None)).first()
    if stock:
        _copy_fields(row, stock)
        bump(stock, user.employee_id)
    item = db.query(WarehouseReceiptItem).filter(WarehouseReceiptItem.id == row.receipt_item_id, WarehouseReceiptItem.deleted_at.is_(None)).first()
    if item:
        _copy_fields(row, item)
        bump(item, user.employee_id)
    op_log(db, user, company_id, "修改", "customs_material", row.id, {"code": row.material_code})
    return row


def delete_material(db, user, company_id, row):
    ensure_creator(row, user)
    if row.invoice_id or row.clearance_id or row.element_id:
        raise BizError("该物料已经被报关发票/报关要素引用，请先解除关联。")
    soft_delete(row, user.employee_id)
    op_log(db, user, company_id, "删除", "customs_material", row.id, {"code": row.material_code})


def batch_assign(db, user, company_id, payload, model=CustomsMaterial):
    ids = [int(item) for item in (payload.get("ids") or [])]
    field = CAMEL.get(payload.get("field"), payload.get("field"))
    if field not in ASSIGN_FIELDS:
        raise BizError("该字段不允许批量赋值")
    if not ids:
        raise BizError("请先勾选记录")
    value = payload.get("value")
    if field == "special_declare":
        value = _bool(value)
    elif field in ("gross_weight", "net_weight", "volume"):
        value = D(value or 0)
    else:
        value = _text(value)
    rows = [get_row(db, model, row_id, company_id) for row_id in sorted(ids)]
    before = [{"id": row.id, field: _vessel_voyage(row=row) if field == "vessel_voyage" else getattr(row, field, "")} for row in rows]
    for row in rows:
        if field == "vessel_voyage":
            name, no = _split_vessel_voyage(value)
            row.vessel_name = name
            row.voyage_no = no
        else:
            setattr(row, field, value)
        bump(row, user.employee_id)
        if model is CustomsMaterial:
            stock = db.query(CustomsStock).filter(CustomsStock.receipt_item_id == row.receipt_item_id, CustomsStock.deleted_at.is_(None)).first()
            item = db.query(WarehouseReceiptItem).filter(WarehouseReceiptItem.id == row.receipt_item_id, WarehouseReceiptItem.deleted_at.is_(None)).first()
            for target in (stock, item):
                if not target:
                    continue
                if field == "vessel_voyage":
                    target.vessel_name = row.vessel_name
                    target.voyage_no = row.voyage_no
                elif hasattr(target, field):
                    setattr(target, field, value)
                bump(target, user.employee_id)
        if model is CustomsStock:
            material = db.query(CustomsMaterial).filter(CustomsMaterial.receipt_item_id == row.receipt_item_id, CustomsMaterial.deleted_at.is_(None)).first()
            item = db.query(WarehouseReceiptItem).filter(WarehouseReceiptItem.id == row.receipt_item_id, WarehouseReceiptItem.deleted_at.is_(None)).first()
            for target in (material, item):
                if not target:
                    continue
                if field == "vessel_voyage":
                    target.vessel_name = row.vessel_name
                    target.voyage_no = row.voyage_no
                elif hasattr(target, field):
                    setattr(target, field, value)
                bump(target, user.employee_id)
    op_log(db, user, company_id, "批量赋值", model.__tablename__, ",".join(str(i) for i in ids), {
        "field": field, "value": value, "count": len(rows), "before": before,
    })
    return len(rows)


def list_stock(db, company_id, params):
    query = q(db, CustomsStock, company_id)
    keyword = _text(params.get("keyword"))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter((CustomsStock.material_code.like(like)) | (CustomsStock.material_name.like(like)) | (CustomsStock.receipt_no.like(like)))
    if _text(params.get("contract_no")):
        query = query.filter(CustomsStock.contract_no == _text(params.get("contract_no")))
    rows = query.order_by(CustomsStock.id.desc()).all()
    return [_item_view(row) for row in rows]


def _picked_materials(db, company_id, ids):
    if not ids:
        raise BizError("请先勾选物料")
    rows = [get_row(db, CustomsMaterial, int(row_id), company_id) for row_id in ids]
    for row in rows:
        errors = missing_fields(row)
        if errors:
            raise BizError(f"{row.material_code} 缺少必填项：{'、'.join(label for _, label in errors)}")
    return rows


def _group_invoice(rows):
    groups = []
    index = {}
    for row in rows:
        if row.special_declare:
            groups.append([row])
            continue
        key = (row.material_category or row.material_name, row.equipment or "", row.unit or "", row.origin_country or "")
        if key not in index:
            index[key] = len(groups)
            groups.append([])
        groups[index[key]].append(row)
    normal = [group for group in groups if not group[0].special_declare]
    special = [group for group in groups if group[0].special_declare]
    return normal + special


def _draft_view(db, build, view):
    """按正式生成规则组好表单，随即回滚，供人工核对后再确认。"""
    savepoint = db.begin_nested()
    try:
        row = build()
        data = dict(view(db, row))
    except Exception:
        savepoint.rollback()
        db.expire_all()
        raise
    savepoint.rollback()
    db.expire_all()
    data["id"] = None
    data["draft"] = True
    return data


def preview_invoice(db, user, company_id, payload):
    return _draft_view(
        db,
        lambda: generate_invoice(db, user, company_id, payload),
        invoice_view,
    )


def preview_clearance(db, user, company_id, payload):
    return _draft_view(
        db,
        lambda: generate_clearance(db, user, company_id, payload),
        clearance_view,
    )


def preview_element(db, user, company_id, payload):
    return _draft_view(
        db,
        lambda: generate_element(db, user, company_id, payload),
        element_view,
    )


def generate_invoice(db, user, company_id, payload):
    rows = _picked_materials(db, company_id, payload.get("ids") or payload.get("material_ids") or [])
    loose = [row.material_code for row in rows if not row.wms_bill_id]
    if loose:
        raise BizError(f"物料 {'、'.join(loose)} 没有对应的采购入库，不能生成报关发票。")
    busy = [row.material_code for row in rows if row.invoice_id]
    if busy:
        raise BizError(f"物料 {'、'.join(busy)} 已生成报关发票")
    code = _text(payload.get("invoice_no")) or next_daily_code(db, CustomsInvoice, company_id, CustomsInvoice.invoice_no, "BG")
    ensure_code_free(db, CustomsInvoice, company_id, CustomsInvoice.invoice_no, code)
    bill_date = parse_date(payload.get("invoice_date")) or date.today()
    rate = month_rate(db, company_id, bill_date)
    invoice = CustomsInvoice(
        invoice_no=code,
        invoice_date=bill_date,
        invoice_date_2=bill_date,
        contract_no=rows[0].contract_no or "",
        packing_list_no=_join_unique(row.packing_list_no for row in rows),
        vessel_voyage=_join_unique(_vessel_voyage(row=row) for row in rows),
        container_no=_join_unique(row.container_no for row in rows),
        bl_no=_join_unique(row.bill_no for row in rows),
        port_of_shipment=_join_unique(getattr(row, "port_of_shipment", "") for row in rows) or DEFAULT_PORT_FROM,
        port_of_destination=_join_unique(getattr(row, "port_of_destination", "") for row in rows) or DEFAULT_PORT_TO,
        payment_terms=_join_unique(getattr(row, "payment_terms", "") for row in rows) or DEFAULT_TERMS,
        consignee=_join_unique(getattr(row, "consignee", "") for row in rows) or DEFAULT_CONSIGNEE,
        po_no=_join_unique(row.po_no for row in rows),
        exchange_rate=rate,
        customs_elements=_join_unique(getattr(row, "declaration_elements", "") for row in rows),
        currency="CNY",
        element_status="未关联",
        status="已生成",
    )
    stamp_new(invoice, user, company_id)
    db.add(invoice)
    db.flush()
    total = ZERO
    for seq, group in enumerate(_group_invoice(rows), start=1):
        qty = sum((D(item.quantity) for item in group), ZERO)
        amount = sum((D(item.price) * D(item.quantity) for item in group), ZERO)
        amount = round2(amount)
        price = round2(amount / qty) if qty else ZERO
        first = group[0]
        db.add(CustomsInvoiceItem(
            invoice_id=invoice.id,
            seq=seq,
            name_cn=first.material_category or first.material_name,
            name_en=first.material_name_en or "",
            specification=first.specification or "",
            quantity=qty,
            unit=first.unit or "",
            price=price,
            amount=amount,
            packages=_packages(group),
            special_declare=bool(first.special_declare),
            category=first.material_category or "",
            equipment=first.equipment or "",
            invoice_no=code,
            company_id=company_id,
            created_by=user.employee_id,
            updated_by=user.employee_id,
            created_at=now(),
            updated_at=now(),
            version=1,
        ))
        total += amount
        for item in group:
            db.add(CustomsInvoiceLink(invoice_id=invoice.id, material_id=item.id, company_id=company_id, created_by=user.employee_id, updated_by=user.employee_id, created_at=now(), updated_at=now(), version=1))
            item.invoice_id = invoice.id
            item.status = "已生成报关单"
            bump(item, user.employee_id)
    invoice.total_amount = round2(total)
    invoice.total_usd = round2(total / rate) if rate else ZERO
    op_log(db, user, company_id, "生成报关发票", "customs_invoice", code, {"materials": [row.id for row in rows]})
    db.flush()
    return invoice


def month_rate(db, company_id, when: date, currency="USD"):
    if when is None:
        when = date.today()
    row = q(db, ExchangeRate, company_id).filter(ExchangeRate.year == when.year, ExchangeRate.month == when.month, ExchangeRate.currency == currency).first()
    return D(row.rate) if row else None


def generate_clearance(db, user, company_id, payload):
    rows = _picked_materials(db, company_id, payload.get("ids") or payload.get("material_ids") or [])
    loose = [row.material_code for row in rows if not row.wms_bill_id]
    if loose:
        raise BizError(f"物料 {'、'.join(loose)} 没有对应的采购入库，不能生成清关发票。")
    busy = [row.material_code for row in rows if row.clearance_id]
    if busy:
        raise BizError(f"物料 {'、'.join(busy)} 已生成清关发票")
    bill_date = parse_date(payload.get("invoice_date")) or date.today()
    rate = _qty(payload.get("exchange_rate")) or month_rate(db, company_id, bill_date)
    bill = CustomsClearance(
        invoice_no=_text(payload.get("invoice_no")) or None,
        invoice_date=bill_date,
        vessel_name=_split_vessel_voyage(payload.get("vessel_voyage"))[0] or _text(payload.get("vessel_name")) or rows[0].vessel_name,
        voyage_no=_split_vessel_voyage(payload.get("vessel_voyage"))[1] or _text(payload.get("voyage_no")) or rows[0].voyage_no,
        container_no=_text(payload.get("container_no")) or "、".join(sorted({row.container_no for row in rows if row.container_no})),
        bill_no=_text(payload.get("bill_no")) or rows[0].bill_no,
        port_of_shipment=_text(payload.get("port_of_shipment")) or _join_unique(getattr(row, "port_of_shipment", "") for row in rows) or DEFAULT_PORT_FROM,
        packing_list_no=_text(payload.get("packing_list_no")) or _join_unique(row.packing_list_no for row in rows),
        exchange_rate=rate,
        status="已生成",
    )
    stamp_new(bill, user, company_id)
    db.add(bill)
    db.flush()
    total = ZERO
    total_usd = ZERO
    for seq, row in enumerate(rows, start=1):
        amount = round2(D(row.price) * D(row.quantity))
        usd = round2(amount / rate) if rate else ZERO
        db.add(CustomsClearanceItem(
            clearance_id=bill.id, material_id=row.id, seq=seq,
            name_cn=row.material_name, name_en=row.material_name_en, specification=row.specification,
            quantity=row.quantity, unit=row.unit, price=row.price, amount=amount, amount_usd=usd,
            po_no=row.po_no, remark=_text(getattr(row, "remark", "")), company_id=company_id, created_by=user.employee_id, updated_by=user.employee_id,
            created_at=now(), updated_at=now(), version=1,
        ))
        total += amount
        total_usd += usd
        row.clearance_id = bill.id
        bump(row, user.employee_id)
    for seq, group in enumerate(_group_invoice(rows), start=1):
        first = group[0]
        db.add(CustomsClearancePl(
            clearance_id=bill.id, seq=seq, category=first.material_category or first.material_name,
            specification=first.specification, quantity=sum((D(item.quantity) for item in group), ZERO),
            unit=first.unit, packages=_package_count(group),
            gross_weight=_sum_optional(group, "gross_weight"),
            net_weight=_sum_optional(group, "net_weight"),
            size_text=_size(first),
            receipt_no=_join_unique(item.receipt_no for item in group),
            company_id=company_id, created_by=user.employee_id, updated_by=user.employee_id,
            created_at=now(), updated_at=now(), version=1,
        ))
    bill.total_amount = round2(total)
    bill.total_usd = round2(total_usd)
    op_log(db, user, company_id, "生成清关发票", "customs_clearance", bill.id, {"materials": [row.id for row in rows]})
    db.flush()
    return bill


def _overlap(left, right):
    a, b = set(left or ""), set(right or "")
    if not a or not b:
        return 0
    return len(a & b) / max(len(a), len(b))


def match_hs(db, company_id, name: str):
    name = _text(name)
    rows = q(db, HsCodeLibrary, company_id).filter(HsCodeLibrary.status == "启用").all()
    exact = [row for row in rows if row.declaration_name == name]
    if exact:
        return [{"hs_code": row.hs_code, "declaration_name": row.declaration_name, "specification": row.specification or "", "declaration_elements": row.declaration_elements or "", "source": "exact", "score": 1, "reason": "申报名称完全一致"} for row in exact]
    fuzzy = []
    for row in rows:
        if name and name in (row.declaration_name or ""):
            score = 0.92
        else:
            score = _overlap(name, row.declaration_name)
        if score >= 0.7:
            fuzzy.append((score, row))
    fuzzy.sort(key=lambda item: item[0], reverse=True)
    result = []
    for score, row in fuzzy[:5]:
        result.append({
            "hs_code": row.hs_code,
            "declaration_name": row.declaration_name,
            "specification": row.specification or "",
            "declaration_elements": row.declaration_elements or "",
            "source": "fuzzy",
            "score": round(score, 2),
            "reason": "自动推荐" if score >= 0.9 else "请人工确认",
        })
    return result


def generate_element(db, user, company_id, payload):
    invoice = get_row(db, CustomsInvoice, payload.get("invoice_id"), company_id)
    if invoice.customs_element_id:
        raise BizError("该报关发票已关联报关要素")
    links = q(db, CustomsInvoiceLink, company_id).filter(CustomsInvoiceLink.invoice_id == invoice.id).all()
    rows = [get_row(db, CustomsMaterial, link.material_id, company_id) for link in links]
    if payload.get("ids"):
        picked = {int(item) for item in payload["ids"]}
        rows = [row for row in rows if row.id in picked] or rows
    element = CustomsElement(invoice_id=invoice.id, status="已生成")
    stamp_new(element, user, company_id)
    db.add(element)
    db.flush()
    for seq, group in enumerate(_group_invoice(rows), start=1):
        first = group[0]
        name = first.material_category or first.material_name
        hits = match_hs(db, company_id, name)
        best = hits[0] if hits else {}
        elements = _join_unique(getattr(item, "declaration_elements", "") for item in group) or best.get("declaration_elements") or ""
        hs_code = _join_unique(getattr(item, "hs_code", "") for item in group) or best.get("hs_code") or ""
        item_row = CustomsElementItem(
            element_id=element.id, seq=seq, hs_code=hs_code,
            declaration_name=name, specification=first.specification or best.get("specification") or "",
            declaration_elements=elements,
            quantity=sum((D(item.quantity) for item in group), ZERO),
            special_declare=bool(first.special_declare),
            match_source=best.get("source") or "",
            match_score=str(best.get("score") or ""),
            company_id=company_id, created_by=user.employee_id, updated_by=user.employee_id,
            created_at=now(), updated_at=now(), version=1,
        )
        db.add(item_row)
        db.flush()
        for line_no, material in enumerate(group, start=1):
            db.add(CustomsElementLine(
                element_item_id=item_row.id, seq=line_no,
                product_name=material.material_name or "",
                model=material.specification or "",
                declaration_elements=elements,
                origin_place=material.origin_country or "",
                company_id=company_id, created_by=user.employee_id, updated_by=user.employee_id,
                created_at=now(), updated_at=now(), version=1,
            ))
        for item in group:
            item.element_id = element.id
            bump(item, user.employee_id)
    invoice.customs_element_id = element.id
    invoice.element_status = "已关联"
    invoice.status = "已关联报关要素"
    bump(invoice, user.employee_id)
    op_log(db, user, company_id, "生成报关要素", "customs_element", element.id, {"invoice": invoice.invoice_no})
    db.flush()
    return element


def compare_element(db, company_id, element: CustomsElement):
    invoice = get_row(db, CustomsInvoice, element.invoice_id, company_id)
    inv_items = q(db, CustomsInvoiceItem, company_id).filter(CustomsInvoiceItem.invoice_id == invoice.id).order_by(CustomsInvoiceItem.seq).all()
    el_items = q(db, CustomsElementItem, company_id).filter(CustomsElementItem.element_id == element.id).order_by(CustomsElementItem.seq).all()
    issues = []
    n = max(len(inv_items), len(el_items))
    for index in range(n):
        left = inv_items[index] if index < len(inv_items) else None
        right = el_items[index] if index < len(el_items) else None
        no = index + 1
        if left and not right:
            issues.append(f"[第{no}行] 报关发票存在但报关要素缺失")
            continue
        if right and not left:
            issues.append(f"[第{no}行] 报关要素存在但报关发票缺失")
            continue
        if (left.name_cn or "") != (right.declaration_name or ""):
            issues.append(f"[第{no}行] 申报名称不一致：报关发票「{left.name_cn}」，报关要素「{right.declaration_name}」")
        if D(left.quantity) != D(right.quantity):
            issues.append(f"[第{no}行] 数量不一致：报关发票 {qty_str(left.quantity)}，报关要素 {qty_str(right.quantity)}")
    return issues


def _package_count(rows):
    explicit = [int(row.package_count) for row in rows if getattr(row, "package_count", None)]
    if explicit:
        return sum(explicit)
    return _packages(rows)


def _money_or_blank(value):
    if value in (None, ""):
        return ""
    return money_str(value)


def _qty_or_blank(value):
    if value in (None, ""):
        return ""
    return qty_str(value)


def _linked_materials(db, row: CustomsInvoice):
    links = q(db, CustomsInvoiceLink, row.company_id).filter(CustomsInvoiceLink.invoice_id == row.id).all()
    materials = []
    for link in links:
        material = db.get(CustomsMaterial, link.material_id)
        if material and not material.deleted_at:
            materials.append(material)
    materials.sort(key=lambda item: item.id)
    return materials


def _category_rows(groups, rate):
    rows = []
    for seq, group in enumerate(groups, start=1):
        first = group[0]
        qty = sum((D(item.quantity) for item in group), ZERO)
        amount = round2(sum((D(item.price) * D(item.quantity) for item in group), ZERO))
        price = round2(amount / qty) if qty else ZERO
        usd = round2(amount / rate) if rate else None
        gross = _sum_optional(group, "gross_weight")
        net = _sum_optional(group, "net_weight")
        specs = _join_unique(item.specification for item in group).split(", ") if any(_text(item.specification) for item in group) else []
        specs = [item for item in specs if item]
        names = [item for item in _join_unique(item.material_name for item in group).split(", ") if item]
        english = [item for item in _join_unique(item.material_name_en for item in group).split(", ") if item]
        rows.append({
            "seq": seq,
            "material_category": first.material_category or first.material_name or "",
            "name_en": english[0] if len(names) == 1 and english else "",
            "specification": specs[0] if len(specs) == 1 else "",
            "quantity": qty_str(qty),
            "unit": first.unit or "",
            "package_count": _package_count(group),
            "gross_weight": _qty_or_blank(gross),
            "net_weight": _qty_or_blank(net),
            "size_display": _group_size(group),
            "weight": _qty_or_blank(gross),
            "container_no": _join_unique(item.container_no for item in group),
            "box_label": _join_unique(item.box_no for item in group) or f"{seq}#",
            "price": money_str(price),
            "amount": money_str(amount),
            "amount_usd": _money_or_blank(usd),
        })
    return rows


def _detail_groups(materials, rate):
    order = []
    buckets = {}
    for row in materials:
        key = _text(row.container_no) or "未填写集装箱"
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(row)
    groups = []
    for index, key in enumerate(order, start=1):
        items = []
        for seq, row in enumerate(buckets[key], start=1):
            total = round2(D(row.price) * D(row.quantity))
            usd = round2(total / rate) if rate else None
            items.append({
                "seq": seq,
                "chinese_name": row.material_name or "",
                "english_name": row.material_name_en or "",
                "model": row.specification or "",
                "unit": row.unit or "",
                "quantity": qty_str(row.quantity),
                "fob_unit_price": money_str(row.price),
                "fob_total_price": money_str(total),
                "convert_to_usd": _money_or_blank(usd),
                "inquiry_name": row.inquiry_name or "",
                "inquiry_model": row.inquiry_model or "",
                "inquiry_qty": _qty_or_blank(row.inquiry_qty),
            })
        groups.append({
            "specification_no": index,
            "label": f"Specification # {index}",
            "container_no": key,
            "items": items,
        })
    return groups


def _invoice_pages(db, row: CustomsInvoice):
    materials = _linked_materials(db, row)
    when = row.invoice_date or date.today()
    rate = D(row.exchange_rate) if row.exchange_rate not in (None, "") else None
    hidden_date = row.invoice_date_2 or row.invoice_date
    detail_groups = _detail_groups(materials, rate)
    identity = _doc_identity(db, materials)
    return {
        "invoice_date_1": dump(row.invoice_date),
        "invoice_date_2": dump(hidden_date),
        "packing_list_no": row.packing_list_no or _join_unique(item.packing_list_no for item in materials),
        "vessel_voyage": row.vessel_voyage or _join_unique(_vessel_voyage(row=item) for item in materials),
        "container_no": row.container_no or _join_unique(item.container_no for item in materials),
        "bl_no": row.bl_no or _join_unique(item.bill_no for item in materials),
        "port_of_shipment": row.port_of_shipment or DEFAULT_PORT_FROM,
        "port_of_destination": row.port_of_destination or DEFAULT_PORT_TO,
        "customs_elements": row.customs_elements or "",
        "exchange_rate": qty_str(rate) if rate is not None else "",
        "total_amount_usd": money_str(row.total_usd or 0),
        "po_no": row.po_no or _join_unique(item.po_no for item in materials),
        "payment_terms": row.payment_terms or DEFAULT_TERMS,
        "consignee": row.consignee or DEFAULT_CONSIGNEE,
        "rate_date": _rate_label(when),
        "supplier_name": identity["supplier_name"],
        "main_materials": identity["main_materials"],
        "categories": _category_rows(_group_invoice(materials), rate) if materials else [],
        "specification_options": [{"label": group["label"], "value": group["container_no"]} for group in detail_groups],
        "detail_groups": detail_groups,
    }


def invoice_view(db, row: CustomsInvoice):
    items = q(db, CustomsInvoiceItem, row.company_id).filter(CustomsInvoiceItem.invoice_id == row.id).order_by(CustomsInvoiceItem.seq).all()
    materials = _linked_materials(db, row)
    pages = _invoice_pages(db, row)
    return {
        "id": row.id, "version": row.version, "invoice_no": row.invoice_no, "invoice_date": dump(row.invoice_date),
        "contract_no": row.contract_no or "", "total_amount": money_str(row.total_amount), "currency": row.currency,
        "customs_element_id": row.customs_element_id, "element_status": row.element_status, "status": row.status,
        "linked": bool(row.customs_element_id), "created_by": row.created_by,
        "items": [{
            "id": item.id, "seq": item.seq, "name_cn": item.name_cn, "name_en": item.name_en, "specification": item.specification,
            "quantity": qty_str(item.quantity), "unit": item.unit, "price": money_str(item.price), "amount": money_str(item.amount),
            "packages": item.packages, "special_declare": item.special_declare, "invoice_no": item.invoice_no,
        } for item in items],
        "sources": [_material_view(item) for item in materials],
        **pages,
    }


def save_invoice(db, user, company_id, row: CustomsInvoice, payload):
    ensure_creator(row, user)
    ensure_version(row, payload.get("version"))
    data = _snake(payload)
    if data.get("invoice_date_1") or data.get("invoice_date"):
        row.invoice_date = parse_date(data.get("invoice_date_1") or data.get("invoice_date")) or row.invoice_date
    if data.get("invoice_date_2"):
        row.invoice_date_2 = parse_date(data.get("invoice_date_2")) or row.invoice_date_2
    elif not row.invoice_date_2:
        row.invoice_date_2 = row.invoice_date
    for key in (
        "packing_list_no", "vessel_voyage", "container_no", "bl_no", "port_of_shipment",
        "port_of_destination", "customs_elements", "payment_terms", "consignee", "po_no", "contract_no",
    ):
        if key in data:
            setattr(row, key, _text(data.get(key)))
    if "exchange_rate" in data:
        row.exchange_rate = _qty(data.get("exchange_rate"))
    if row.exchange_rate:
        row.total_usd = round2(D(row.total_amount) / D(row.exchange_rate))
    bump(row, user.employee_id)
    op_log(db, user, company_id, "修改", "customs_invoice", row.invoice_no, {})
    return row


def _clearance_materials(db, row: CustomsClearance):
    return q(db, CustomsMaterial, row.company_id).filter(CustomsMaterial.clearance_id == row.id).order_by(CustomsMaterial.id).all()


def clearance_view(db, row: CustomsClearance):
    items = q(db, CustomsClearanceItem, row.company_id).filter(CustomsClearanceItem.clearance_id == row.id).order_by(CustomsClearanceItem.seq).all()
    pls = q(db, CustomsClearancePl, row.company_id).filter(CustomsClearancePl.clearance_id == row.id).order_by(CustomsClearancePl.seq).all()
    materials = _clearance_materials(db, row)
    groups = {}
    for group in _group_invoice(materials):
        first = group[0]
        groups.setdefault(first.material_category or first.material_name or "", group)
    return {
        "id": row.id, "version": row.version, "invoice_no": row.invoice_no or "", "invoice_missing": not bool(row.invoice_no),
        "invoice_date": dump(row.invoice_date), "vessel_name": row.vessel_name or "", "voyage_no": row.voyage_no or "",
        "vessel_voyage": _vessel_voyage(row.vessel_name, row.voyage_no),
        "container_no": row.container_no or "", "bill_no": row.bill_no or "",
        "port_of_shipment": row.port_of_shipment or DEFAULT_PORT_FROM,
        "packing_list_no": row.packing_list_no or _join_unique(item.packing_list_no for item in materials),
        "exchange_rate": qty_str(row.exchange_rate) if row.exchange_rate is not None else "",
        "total_amount": money_str(row.total_amount), "total_usd": money_str(row.total_usd), "status": row.status,
        "created_by": row.created_by,
        **_doc_identity(db, materials),
        "items": [{
            "id": item.id, "seq": item.seq, "name_cn": item.name_cn, "name_en": item.name_en, "specification": item.specification,
            "quantity": qty_str(item.quantity), "unit": item.unit or "", "price": money_str(item.price), "amount": money_str(item.amount),
            "amount_usd": money_str(item.amount_usd), "po_no": item.po_no or "", "remark": item.remark or "",
        } for item in items],
        "packing": [{
            "id": item.id, "seq": item.seq, "category": item.category, "specification": item.specification,
            "quantity": qty_str(item.quantity), "unit": item.unit or "", "packages": item.packages,
            "gross_weight": qty_str(item.gross_weight) if item.gross_weight is not None else "",
            "net_weight": qty_str(item.net_weight) if item.net_weight is not None else "",
            "size_text": item.size_text or "",
            "receipt_no": item.receipt_no or _join_unique(material.receipt_no for material in groups.get(item.category or "", [])),
        } for item in pls],
    }


def _money_in(value):
    return D(str(value or "0").replace(",", ""))


def save_clearance(db, user, company_id, row: CustomsClearance, payload):
    """已生成发票号或已导出，仍然允许修改。"""
    ensure_creator(row, user)
    ensure_version(row, payload.get("version"))
    data = _snake(payload)
    if "invoice_no" in data:
        row.invoice_no = _text(data.get("invoice_no")) or None
    if data.get("invoice_date"):
        row.invoice_date = parse_date(data.get("invoice_date")) or row.invoice_date
    if "vessel_voyage" in data:
        row.vessel_name, row.voyage_no = _split_vessel_voyage(data.get("vessel_voyage"))
    for key in ("container_no", "bill_no", "port_of_shipment", "packing_list_no"):
        if key in data:
            setattr(row, key, _text(data.get(key)))
    if "exchange_rate" in data:
        row.exchange_rate = _qty(data.get("exchange_rate"))
    rate = D(row.exchange_rate) if row.exchange_rate not in (None, "") else None
    if isinstance(payload.get("items"), list):
        existing = q(db, CustomsClearanceItem, company_id).filter(CustomsClearanceItem.clearance_id == row.id).order_by(CustomsClearanceItem.seq).all()
        total = ZERO
        total_usd = ZERO
        for index, raw in enumerate(payload["items"]):
            item = existing[index] if index < len(existing) else None
            if item is None:
                continue
            item.seq = index + 1
            item.name_cn = _text(raw.get("name_cn"))
            item.name_en = _text(raw.get("name_en"))
            item.specification = _text(raw.get("specification"))
            item.quantity = _money_in(raw.get("quantity"))
            item.unit = _text(raw.get("unit"))
            item.price = _money_in(raw.get("price"))
            item.amount = round2(D(item.price) * D(item.quantity))
            item.amount_usd = round2(D(item.amount) / rate) if rate else ZERO
            item.po_no = _text(raw.get("po_no"))
            item.remark = _text(raw.get("remark"))
            item.updated_by = user.employee_id
            item.updated_at = now()
            total += D(item.amount)
            total_usd += D(item.amount_usd)
        row.total_amount = round2(total)
        row.total_usd = round2(total_usd)
    if isinstance(payload.get("packing"), list):
        existing = q(db, CustomsClearancePl, company_id).filter(CustomsClearancePl.clearance_id == row.id).order_by(CustomsClearancePl.seq).all()
        for index, raw in enumerate(payload["packing"]):
            item = existing[index] if index < len(existing) else None
            if item is None:
                continue
            item.seq = index + 1
            item.category = _text(raw.get("category"))
            item.specification = _text(raw.get("specification"))
            item.quantity = _money_in(raw.get("quantity"))
            item.unit = _text(raw.get("unit"))
            packages = _text(raw.get("packages"))
            item.packages = int(D(packages or 0))
            item.gross_weight = _qty(raw.get("gross_weight"))
            item.net_weight = _qty(raw.get("net_weight"))
            item.size_text = _text(raw.get("size_text"))
            item.receipt_no = _text(raw.get("receipt_no"))
            item.updated_by = user.employee_id
            item.updated_at = now()
    bump(row, user.employee_id)
    op_log(db, user, company_id, "修改", "customs_clearance", row.invoice_no or row.id, {})
    return row


def _fallback_lines(db, company_id, element_id, item: CustomsElementItem):
    materials = q(db, CustomsMaterial, company_id).filter(CustomsMaterial.element_id == element_id).order_by(CustomsMaterial.id).all()
    groups = _group_invoice(materials)
    chosen = []
    for group in groups:
        first = group[0]
        if (first.material_category or first.material_name) == (item.declaration_name or ""):
            chosen = group
            break
    if not chosen and 0 < item.seq <= len(groups):
        chosen = groups[item.seq - 1]
    if chosen:
        return [{
            "id": None, "seq": index, "product_name": material.material_name or "",
            "model": material.specification or item.specification or "",
            "declaration_elements": _text(getattr(material, "declaration_elements", "")) or item.declaration_elements or "",
            "origin_place": material.origin_country or "",
        } for index, material in enumerate(chosen, start=1)]
    return [{
        "id": None, "seq": 1, "product_name": "",
        "model": item.specification or "", "declaration_elements": item.declaration_elements or "",
        "origin_place": "",
    }]


def _element_lines(db, company_id, element_id, item: CustomsElementItem):
    lines = q(db, CustomsElementLine, company_id).filter(CustomsElementLine.element_item_id == item.id).order_by(CustomsElementLine.seq).all()
    if lines:
        return [{
            "id": line.id, "seq": line.seq, "product_name": line.product_name or "",
            "model": line.model or "", "declaration_elements": line.declaration_elements or "",
            "origin_place": line.origin_place or "",
        } for line in lines]
    return _fallback_lines(db, company_id, element_id, item)


def _element_materials(db, row: CustomsElement):
    materials = q(db, CustomsMaterial, row.company_id).filter(CustomsMaterial.element_id == row.id).order_by(CustomsMaterial.id).all()
    if materials:
        return materials
    invoice = db.get(CustomsInvoice, row.invoice_id)
    return _linked_materials(db, invoice) if invoice else []


def _element_item_view(db, row, item):
    lines = _element_lines(db, row.company_id, row.id, item)
    shared = item.declaration_elements or _join_unique(line.get("declaration_elements") for line in lines)
    for line in lines:
        line["declaration_elements"] = shared
    return {
        "id": item.id, "seq": item.seq, "hs_code": item.hs_code or "", "declaration_name": item.declaration_name or "",
        "specification": item.specification or "", "declaration_elements": shared,
        "quantity": qty_str(item.quantity), "special_declare": item.special_declare,
        "match_source": item.match_source or "", "match_score": item.match_score or "",
        "ai_suggestion": item.ai_suggestion or "",
        "lines": lines,
    }


def element_view(db, row: CustomsElement):
    items = q(db, CustomsElementItem, row.company_id).filter(CustomsElementItem.element_id == row.id).order_by(CustomsElementItem.seq).all()
    invoice = db.get(CustomsInvoice, row.invoice_id)
    identity = _doc_identity(db, _element_materials(db, row))
    if invoice and invoice.contract_no:
        identity["contract_no"] = invoice.contract_no
    return {
        "id": row.id, "version": row.version, "invoice_id": row.invoice_id,
        "invoice_no": invoice.invoice_no if invoice else "", "status": row.status, "created_by": row.created_by,
        **identity,
        "issues": compare_element(db, row.company_id, row),
        "items": [_element_item_view(db, row, item) for item in items],
    }


def _replace_element_lines(db, user, company_id, item, raw_lines):
    old = q(db, CustomsElementLine, company_id).filter(CustomsElementLine.element_item_id == item.id).all()
    for line in old:
        soft_delete(line, user.employee_id)
    db.flush()
    for seq, raw in enumerate(raw_lines, start=1):
        line = CustomsElementLine(
            element_item_id=item.id,
            seq=seq,
            product_name=_text(raw.get("product_name")),
            model=_text(raw.get("model") or raw.get("specification")),
            declaration_elements=_text(raw.get("declaration_elements")),
            origin_place=_text(raw.get("origin_place")),
        )
        stamp_new(line, user, company_id)
        db.add(line)


def save_element_items(db, user, company_id, row, payload, confirm=False):
    ensure_creator(row, user)
    ensure_version(row, payload.get("version"))
    incoming = payload.get("items") or []
    existing = q(db, CustomsElementItem, company_id).filter(CustomsElementItem.element_id == row.id).order_by(CustomsElementItem.seq).all()
    for index, raw in enumerate(incoming):
        item = existing[index] if index < len(existing) else CustomsElementItem(element_id=row.id, company_id=company_id, created_by=user.employee_id, created_at=now(), version=1)
        if item.id is None:
            db.add(item)
        item.seq = index + 1
        item.hs_code = _text(raw.get("hs_code"))
        item.declaration_name = _text(raw.get("declaration_name"))
        item.quantity = D(raw.get("quantity") or 0)
        raw_lines = raw.get("lines") or [{
            "product_name": "",
            "model": raw.get("specification") or "",
            "declaration_elements": raw.get("declaration_elements") or "",
            "origin_place": "",
        }]
        first_line = raw_lines[0]
        item.specification = _text(first_line.get("model") or first_line.get("specification") or raw.get("specification"))
        shared_elements = _text(raw.get("declaration_elements") or first_line.get("declaration_elements"))
        item.declaration_elements = shared_elements
        for raw_line in raw_lines:
            raw_line["declaration_elements"] = shared_elements
        item.updated_by = user.employee_id
        item.updated_at = now()
        if item.id is None:
            db.add(item)
            db.flush()
        _replace_element_lines(db, user, company_id, item, raw_lines)
    issues = compare_element(db, company_id, row)
    if issues and not confirm:
        raise BizError("报关要素与报关发票不一致", data={"issues": issues})
    row.status = "已检查"
    bump(row, user.employee_id)
    invoice = get_row(db, CustomsInvoice, row.invoice_id, company_id)
    invoice.status = "已检查"
    bump(invoice, user.employee_id)
    op_log(db, user, company_id, "修改", "customs_element", row.id, {"issues": issues})
    return issues


def _group_materials(db, company_id, attr, ids):
    grouped = {}
    if not ids:
        return grouped
    rows = q(db, CustomsMaterial, company_id).filter(getattr(CustomsMaterial, attr).in_(list(ids))).all()
    for row in rows:
        grouped.setdefault(getattr(row, attr), []).append(row)
    return grouped


def _doc_identity(db, materials, parents=None):
    """列表和表头用：供应商、主要物料、合同号，用来区分单据。"""
    materials = list(materials or [])
    if parents is None:
        parents = _material_parents(db, materials)
    suppliers, names, contracts = [], [], []
    specials = []
    for row in materials:
        category = _text(row.material_category) or _text(row.material_name)
        contract = _text(row.contract_no)
        supplier = _text((parents.get(row.id) or {}).get("supplier_name"))
        for bucket, value in ((contracts, contract), (suppliers, supplier)):
            if value and value not in bucket:
                bucket.append(value)
        if not category:
            continue
        if row.special_declare:
            if category not in specials:
                specials.append(category)
        elif category not in names:
            names.append(category)
    for category in specials:
        if category not in names:
            names.append(category)
    return {
        "supplier_name": "、".join(suppliers),
        "main_materials": "、".join(names),
        "contract_no": "、".join(contracts),
    }


def _identities(db, grouped):
    flat = [row for rows in grouped.values() for row in rows]
    parents = _material_parents(db, flat)
    return {key: _doc_identity(db, rows, parents) for key, rows in grouped.items()}


def unused_invoices(db, company_id, material_ids=None):
    rows = q(db, CustomsInvoice, company_id).filter(CustomsInvoice.customs_element_id.is_(None)).order_by(CustomsInvoice.id.desc()).all()
    if material_ids:
        ids = []
        for raw in material_ids:
            text = _text(raw)
            if text.isdigit():
                ids.append(int(text))
        linked = set()
        if ids:
            for row in q(db, CustomsMaterial, company_id).filter(CustomsMaterial.id.in_(ids)).all():
                if row.invoice_id:
                    linked.add(row.invoice_id)
            for link in q(db, CustomsInvoiceLink, company_id).filter(CustomsInvoiceLink.material_id.in_(ids)).all():
                if link.invoice_id:
                    linked.add(link.invoice_id)
        rows = [row for row in rows if row.id in linked]
    return [{"id": row.id, "invoice_no": row.invoice_no, "contract_no": row.contract_no or ""} for row in rows]


def delete_invoice(db, user, company_id, row):
    ensure_creator(row, user)
    if row.customs_element_id:
        raise BizError("该物料已经被报关发票/报关要素引用，请先解除关联。")
    for link in q(db, CustomsInvoiceLink, company_id).filter(CustomsInvoiceLink.invoice_id == row.id).all():
        material = db.get(CustomsMaterial, link.material_id)
        if material:
            material.invoice_id = None
            material.status = "正常"
            bump(material, user.employee_id)
        soft_delete(link, user.employee_id)
    for item in q(db, CustomsInvoiceItem, company_id).filter(CustomsInvoiceItem.invoice_id == row.id).all():
        soft_delete(item, user.employee_id)
    soft_delete(row, user.employee_id)
    op_log(db, user, company_id, "删除", "customs_invoice", row.invoice_no, {})


def delete_clearance(db, user, company_id, row):
    ensure_creator(row, user)
    for item in q(db, CustomsClearanceItem, company_id).filter(CustomsClearanceItem.clearance_id == row.id).all():
        if item.material_id:
            material = db.get(CustomsMaterial, item.material_id)
            if material:
                material.clearance_id = None
                bump(material, user.employee_id)
        soft_delete(item, user.employee_id)
    for item in q(db, CustomsClearancePl, company_id).filter(CustomsClearancePl.clearance_id == row.id).all():
        soft_delete(item, user.employee_id)
    soft_delete(row, user.employee_id)
    op_log(db, user, company_id, "删除", "customs_clearance", row.id, {})


def delete_element(db, user, company_id, row):
    ensure_creator(row, user)
    invoice = get_row(db, CustomsInvoice, row.invoice_id, company_id)
    invoice.customs_element_id = None
    invoice.element_status = "未关联"
    invoice.status = "已生成"
    bump(invoice, user.employee_id)
    for item in q(db, CustomsMaterial, company_id).filter(CustomsMaterial.element_id == row.id).all():
        item.element_id = None
        bump(item, user.employee_id)
    for item in q(db, CustomsElementItem, company_id).filter(CustomsElementItem.element_id == row.id).all():
        for line in q(db, CustomsElementLine, company_id).filter(CustomsElementLine.element_item_id == item.id).all():
            soft_delete(line, user.employee_id)
        soft_delete(item, user.employee_id)
    soft_delete(row, user.employee_id)
    op_log(db, user, company_id, "删除", "customs_element", row.id, {})


def save_hs(db, user, company_id, payload, row):
    code = _text(payload.get("hs_code"))
    name = _text(payload.get("declaration_name"))
    if not code or not name:
        raise BizError("HS Code 和申报名称不能为空")
    if row:
        ensure_version(row, payload.get("version"))
        bump(row, user.employee_id)
    else:
        dup = q(db, HsCodeLibrary, company_id).filter(HsCodeLibrary.hs_code == code, HsCodeLibrary.declaration_name == name).first()
        if dup:
            raise BizError("HS Code 已存在")
        row = HsCodeLibrary()
        stamp_new(row, user, company_id)
        db.add(row)
    row.hs_code = code
    row.declaration_name = name
    row.product_name = _text(payload.get("product_name"))
    row.specification = _text(payload.get("specification"))
    row.declaration_elements = _text(payload.get("declaration_elements"))
    row.description = _text(payload.get("description"))
    row.status = payload.get("status") or "启用"
    db.flush()
    return row


def save_rate(db, user, company_id, payload, row):
    year = int(payload.get("year") or date.today().year)
    month = int(payload.get("month") or date.today().month)
    currency = _text(payload.get("currency")) or "USD"
    rate = D(payload.get("rate") or 0)
    if rate <= 0:
        raise BizError("汇率必须大于 0")
    if row:
        ensure_version(row, payload.get("version"))
        bump(row, user.employee_id)
    else:
        dup = q(db, ExchangeRate, company_id).filter(ExchangeRate.year == year, ExchangeRate.month == month, ExchangeRate.currency == currency).first()
        if dup:
            raise BizError("该月汇率已存在")
        row = ExchangeRate()
        stamp_new(row, user, company_id)
        db.add(row)
    row.year = year
    row.month = month
    row.currency = currency
    row.rate = rate
    row.effective_date = parse_date(payload.get("effective_date")) or date(year, month, 1)
    db.flush()
    return row


def list_hs(db, company_id, params):
    query = q(db, HsCodeLibrary, company_id)
    keyword = _text(params.get("keyword"))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (HsCodeLibrary.hs_code.like(like))
            | (HsCodeLibrary.declaration_name.like(like))
            | (HsCodeLibrary.product_name.like(like))
        )
    rows = query.order_by(HsCodeLibrary.id.desc()).all()
    return [{
        "id": row.id, "version": row.version, "hs_code": row.hs_code, "declaration_name": row.declaration_name,
        "product_name": row.product_name or "",
        "specification": row.specification or "", "declaration_elements": row.declaration_elements or "",
        "description": row.description or "", "status": row.status, "created_by": row.created_by,
    } for row in rows]


def list_rates(db, company_id, params):
    query = q(db, ExchangeRate, company_id)
    if params.get("year"):
        query = query.filter(ExchangeRate.year == int(params.get("year")))
    if params.get("month"):
        query = query.filter(ExchangeRate.month == int(params.get("month")))
    if params.get("currency"):
        query = query.filter(ExchangeRate.currency == params.get("currency"))
    rows = query.order_by(ExchangeRate.year.desc(), ExchangeRate.month.desc()).all()
    keyword = _text(params.get("keyword")).lower()
    items = [{
        "id": row.id, "version": row.version, "year": row.year, "month": row.month, "currency": row.currency,
        "rate": qty_str(row.rate), "effective_date": dump(row.effective_date), "created_by": row.created_by,
    } for row in rows]
    if keyword:
        items = [item for item in items if keyword in f"{item['year']} {item['month']} {item['currency']} {item['rate']}".lower()]
    return items


def save_file(db, user, company_id, business_type, business_id, filename, content: bytes):
    name = Path(filename or "file").name
    folder = UPLOAD_DIR / "customs" / str(company_id)
    folder.mkdir(parents=True, exist_ok=True)
    row = BizFile(
        file_name=name, file_path="", file_type=Path(name).suffix.lower(), file_size=len(content or b""),
        business_type=business_type, business_id=int(business_id), status="启用",
    )
    stamp_new(row, user, company_id)
    db.add(row)
    db.flush()
    path = folder / f"{row.id}_{name}"
    path.write_bytes(content or b"")
    row.file_path = str(path)
    op_log(db, user, company_id, "上传附件", business_type, business_id, {"file": name})
    return row


def list_files(db, company_id, business_type, business_id):
    query = q(db, BizFile, company_id).filter(BizFile.status == "启用")
    if business_type:
        query = query.filter(BizFile.business_type == business_type)
    if business_id:
        query = query.filter(BizFile.business_id == int(business_id))
    rows = query.order_by(BizFile.id.desc()).all()
    return [{"id": row.id, "version": row.version, "file_name": row.file_name, "file_type": row.file_type, "file_size": row.file_size, "business_type": row.business_type, "business_id": row.business_id, "created_at": dump(row.created_at)} for row in rows]


def remove_file(db, user, company_id, row):
    row.status = "停用"
    bump(row, user.employee_id)
    op_log(db, user, company_id, "删除附件", row.business_type, row.business_id, {"file": row.file_name})


DEEPSEEK_MODELS = (
    {"value": "deepseek-v4-flash", "label": "V4 Flash（办公）"},
    {"value": "deepseek-flash", "label": "V4.1 Flash"},
    {"value": "deepseek-v4-pro", "label": "V4 Pro"},
)
DEEPSEEK_DEFAULT_KEY = ""


def _deepseek_cfg(payload):
    timeout = int(payload.get("timeout_seconds") or 30)
    timeout = min(120, max(5, timeout))
    try:
        temperature = float(payload.get("temperature") if payload.get("temperature") not in (None, "") else 0.2)
    except (TypeError, ValueError):
        temperature = 0.2
    base = _text(payload.get("api_base")) or "https://api.deepseek.com"
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return type("Cfg", (), {
        "api_base": base,
        "api_key": _text(payload.get("api_key")),
        "model": _text(payload.get("model")) or "deepseek-v4-flash",
        "timeout_seconds": timeout,
        "temperature": temperature,
        "thinking": bool(payload.get("thinking")),
    })()


def deepseek_view(row):
    return {
        "id": row.id,
        "version": row.version,
        "enabled": bool(row.enabled),
        "api_base": row.api_base or "https://api.deepseek.com",
        "api_key": row.api_key or "",
        "model": row.model or "deepseek-v4-flash",
        "timeout_seconds": int(row.timeout_seconds or 30),
        "temperature": float(row.temperature or "0.2"),
        "thinking": bool(row.thinking),
        "models": list(DEEPSEEK_MODELS),
    }


def ensure_deepseek_settings(db):
    from ..models import Company

    companies = db.query(Company).filter(Company.deleted_at.is_(None)).all()
    for company in companies:
        exists = (
            db.query(DeepseekSetting)
            .filter(DeepseekSetting.company_id == company.id, DeepseekSetting.deleted_at.is_(None))
            .first()
        )
        if exists:
            continue
        row = DeepseekSetting(
            enabled=True,
            api_base="https://api.deepseek.com",
            api_key=DEEPSEEK_DEFAULT_KEY,
            model="deepseek-v4-flash",
            timeout_seconds=30,
            temperature="0.2",
            thinking=False,
        )
        row.company_id = company.id
        row.created_by = "admin"
        row.updated_by = "admin"
        row.created_at = now()
        row.updated_at = now()
        row.version = 1
        db.add(row)
    db.flush()


def deepseek_row(db, company_id, user):
    row = q(db, DeepseekSetting, company_id).first()
    if row:
        return row
    row = DeepseekSetting(
        enabled=True,
        api_base="https://api.deepseek.com",
        api_key=DEEPSEEK_DEFAULT_KEY,
        model="deepseek-v4-flash",
        timeout_seconds=30,
        temperature="0.2",
        thinking=False,
    )
    stamp_new(row, user, company_id)
    db.add(row)
    db.flush()
    return row


def save_deepseek(db, user, company_id, payload):
    row = deepseek_row(db, company_id, user)
    ensure_version(row, payload.get("version"))
    cfg = _deepseek_cfg(payload)
    if cfg.temperature < 0 or cfg.temperature > 2:
        raise BizError("温度需在 0 到 2 之间")
    row.enabled = bool(payload.get("enabled"))
    row.api_base = cfg.api_base
    row.api_key = cfg.api_key
    row.model = cfg.model
    row.timeout_seconds = cfg.timeout_seconds
    row.temperature = f"{cfg.temperature:.1f}"
    row.thinking = cfg.thinking
    bump(row, user.employee_id)
    return row


def _chat_url(base: str) -> str:
    return f"{(base or 'https://api.deepseek.com').rstrip('/')}/chat/completions"


def _deepseek_complete(cfg, messages, json_mode=False):
    from urllib.error import HTTPError

    if not cfg.api_key:
        raise BizError("请先填写 API Key")
    body = {
        "model": cfg.model or "deepseek-v4-flash",
        "messages": messages,
        "temperature": float(cfg.temperature or 0.2),
        "max_tokens": 4096 if cfg.thinking else 1024,
        "stream": False,
        "thinking": {"type": "enabled" if cfg.thinking else "disabled"},
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        _chat_url(cfg.api_base),
        data=data,
        headers={"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=int(cfg.timeout_seconds or 30)) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise BizError(f"DeepSeek 返回 {exc.code}：{detail}") from exc
    message = ((raw.get("choices") or [{}])[0].get("message") or {})
    text = message.get("content") or message.get("reasoning_content") or ""
    if not str(text).strip():
        raise BizError("DeepSeek 没有返回内容")
    return str(text)


def _json_object(text):
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise BizError("模型没有返回 JSON")
    return json.loads(raw[start:end + 1])


def probe_deepseek(payload):
    text = _deepseek_complete(
        _deepseek_cfg(payload),
        [{"role": "user", "content": "只回复两个字母 ok"}],
        json_mode=False,
    )
    return {"ok": True, "reply": text.strip()[:200]}


def ai_check(db, company_id, payload):
    name = _text(payload.get("declarationName") or payload.get("declaration_name"))
    hs = _text(payload.get("hsCode") or payload.get("hs_code"))
    elements = _text(payload.get("elements") or payload.get("declaration_elements"))
    issues = []
    if not name:
        issues.append("申报名称为空")
    if not hs:
        issues.append("HS Code 为空")
    if not elements:
        issues.append("报关要素不完整")
    row = q(db, DeepseekSetting, company_id).first()
    key = (row.api_key if row and row.enabled else "") or ""
    if not key:
        key = os.environ.get("DEEPSEEK_API_KEY") or ""
    if not row or not row.enabled or not key:
        return {"match": not issues, "score": 0.0 if issues else 0.6, "suggestion": "未启用 DeepSeek，仅做本地必填检查", "issues": issues, "source": "local"}
    cfg = _deepseek_cfg({
        "api_base": row.api_base,
        "api_key": key,
        "model": row.model,
        "timeout_seconds": row.timeout_seconds,
        "temperature": row.temperature,
        "thinking": row.thinking,
    })
    prompt = (
        "你是报关资料核对助手。根据申报名称、HS Code 和报关要素，判断三者是否相互匹配。"
        "只返回 JSON，字段为 match（布尔）、score（0到1的小数）、suggestion（中文一句话）、issues（字符串数组）。"
        f"申报名称:{name}; HS:{hs}; 要素:{elements}"
    )
    try:
        text = _deepseek_complete(cfg, [{"role": "user", "content": prompt}], json_mode=True)
        data = _json_object(text)
        data.setdefault("issues", issues)
        data["source"] = "deepseek"
        return data
    except Exception as exc:
        return {"match": not issues, "score": 0, "suggestion": "AI 检查暂时不可用，已跳过，不影响业务保存", "issues": issues + [str(exc)], "source": "fallback"}


def _page(rows, params):
    from .util import page_args
    page_no, size = page_args(params.get("page"), params.get("pageSize"))
    start = (page_no - 1) * size
    return rows[start:start + size], len(rows), page_no, size


def list_invoices(db, company_id, params):
    query = q(db, CustomsInvoice, company_id)
    keyword = _text(params.get("keyword"))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter((CustomsInvoice.invoice_no.like(like)) | (CustomsInvoice.contract_no.like(like)))
    if _text(params.get("contract_no")):
        query = query.filter(CustomsInvoice.contract_no == _text(params.get("contract_no")))
    if _text(params.get("element_status")):
        query = query.filter(CustomsInvoice.element_status == _text(params.get("element_status")))
    rows = query.order_by(CustomsInvoice.id.desc()).all()
    identities = _identities(db, _group_materials(db, company_id, "invoice_id", [row.id for row in rows]))
    items = []
    for row in rows:
        brief = identities.get(row.id) or _doc_identity(db, [])
        items.append({
            "id": row.id, "version": row.version, "invoice_no": row.invoice_no, "invoice_date": dump(row.invoice_date),
            "contract_no": row.contract_no or brief["contract_no"], "total_amount": money_str(row.total_amount), "currency": row.currency,
            "customs_element_id": row.customs_element_id, "element_status": row.element_status, "status": row.status,
            "linked": bool(row.customs_element_id), "created_by": row.created_by,
            "supplier_name": brief["supplier_name"], "main_materials": brief["main_materials"],
        })
    return items


def list_clearances(db, company_id, params):
    query = q(db, CustomsClearance, company_id)
    keyword = _text(params.get("keyword"))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter((CustomsClearance.invoice_no.like(like)) | (CustomsClearance.bill_no.like(like)) | (CustomsClearance.container_no.like(like)))
    rows = query.order_by(CustomsClearance.id.desc()).all()
    identities = _identities(db, _group_materials(db, company_id, "clearance_id", [row.id for row in rows]))
    items = []
    for row in rows:
        brief = identities.get(row.id) or _doc_identity(db, [])
        items.append({
            "id": row.id, "version": row.version,
            "invoice_no": row.invoice_no or "无发票号", "invoice_missing": not bool(row.invoice_no),
            "invoice_date": dump(row.invoice_date), "vessel_name": row.vessel_name or "", "voyage_no": row.voyage_no or "",
            "vessel_voyage": _vessel_voyage(row.vessel_name, row.voyage_no),
            "container_no": row.container_no or "", "bill_no": row.bill_no or "",
            "exchange_rate": qty_str(row.exchange_rate) if row.exchange_rate is not None else "",
            "total_amount": money_str(row.total_amount), "total_usd": money_str(row.total_usd), "status": row.status,
            "created_by": row.created_by, "contract_no": brief["contract_no"],
            "supplier_name": brief["supplier_name"], "main_materials": brief["main_materials"],
        })
    return items


def list_elements(db, company_id, params):
    query = q(db, CustomsElement, company_id)
    rows = query.order_by(CustomsElement.id.desc()).all()
    identities = _identities(db, _group_materials(db, company_id, "element_id", [row.id for row in rows]))
    items = []
    for row in rows:
        invoice = db.get(CustomsInvoice, row.invoice_id)
        brief = identities.get(row.id) or _doc_identity(db, [])
        contract_no = (invoice.contract_no if invoice and invoice.contract_no else "") or brief["contract_no"]
        if _text(params.get("keyword")):
            text = " ".join([
                invoice.invoice_no if invoice else "",
                contract_no,
                brief["supplier_name"],
                brief["main_materials"],
                str(row.id),
            ])
            if _text(params.get("keyword")) not in text:
                continue
        items.append({
            "id": row.id, "version": row.version, "invoice_id": row.invoice_id,
            "invoice_no": invoice.invoice_no if invoice else "", "contract_no": contract_no,
            "status": row.status, "created_by": row.created_by,
            "supplier_name": brief["supplier_name"], "main_materials": brief["main_materials"],
            "issue_count": len(compare_element(db, company_id, row)),
        })
    return items


def mark_exported(db, user, row):
    row.status = "已导出"
    bump(row, user.employee_id)


FILL_HEADERS = {
    "物料编号": "material_code", "入仓单号": "receipt_no",
    "产地": "origin_country", "箱号": "box_no", "尺寸": "size",
    "长": "length", "宽": "width", "高": "height",
    "净重": "net_weight", "毛重": "gross_weight", "体积": "volume",
    "出发港": "port_of_shipment", "出发港口": "port_of_shipment", "目的港": "port_of_destination",
    "集装箱号": "container_no", "提单号": "bill_no", "船名/航号": "vessel_voyage",
    "箱单号": "packing_list_no", "物料大类": "material_category", "使用设备": "equipment",
    "HS Code": "hs_code", "HSCODE": "hs_code", "收货人": "consignee", "包件件数": "package_count",
    "付款条款": "payment_terms", "申报要素": "declaration_elements", "备注": "remark",
}
FILL_QTY = ("length", "width", "height", "net_weight", "gross_weight", "volume")
FILL_TEXT = (
    "origin_country", "box_no", "port_of_shipment", "port_of_destination", "container_no", "bill_no",
    "packing_list_no", "material_category", "equipment", "hs_code", "consignee", "payment_terms",
    "declaration_elements", "remark",
)
FILL_MIRROR = FILL_QTY + FILL_TEXT + ("package_count", "vessel_name", "voyage_no")


def _parse_size_text(value):
    text = _text(value)
    if not text:
        return None
    normalized = text.replace("×", "*").replace("＊", "*").replace("x", "*").replace("X", "*")
    parts = [part.strip() for part in normalized.split("*")]
    if len(parts) != 3 or any(not part for part in parts):
        raise BizError("尺寸格式应为长*宽*高")
    return tuple(D(part) for part in parts)


def _fill_number(label, value, whole=False):
    if not _text(value):
        return ""
    try:
        number = D(value)
    except BizError:
        return f"{label}格式不正确"
    if whole and number != number.to_integral_value():
        return f"{label}必须是整数"
    return ""


def _fill_conflicts(rows):
    groups = {}
    for row in rows:
        payload = row.get("payload") or {}
        code = _text(payload.get("material_code"))
        if not code:
            continue
        groups.setdefault(code, []).append(_text(payload.get("receipt_no")))
    bad = set()
    for code, receipts in groups.items():
        if len(receipts) < 2:
            continue
        if any(not item for item in receipts) or len(set(receipts)) != len(receipts):
            bad.add(code)
    return bad


def _match_materials(db, company_id, code, receipt_no):
    rows = q(db, CustomsMaterial, company_id).filter(CustomsMaterial.material_code == code).all()
    receipt_no = _text(receipt_no)
    if not receipt_no:
        return rows
    exact = [row for row in rows if _text(row.receipt_no) == receipt_no]
    if exact:
        return exact
    # 系统里还没有入仓单号时，表中的入仓单号是要写入的值，不是已存在的查找条件。
    # 同一物料编号有多条时仍必须靠已有入仓单号区分，避免写错行。
    if len(rows) == 1 and not _text(rows[0].receipt_no):
        return rows
    return []


def _validate_fill_payload(payload):
    if not _text(payload.get("material_code")):
        return "物料编号不能为空"
    if _text(payload.get("size")):
        try:
            _parse_size_text(payload.get("size"))
        except BizError:
            return "尺寸格式应为长*宽*高"
    for key, label in (
        ("length", "长"), ("width", "宽"), ("height", "高"),
        ("net_weight", "净重"), ("gross_weight", "毛重"), ("volume", "体积"),
    ):
        message = _fill_number(label, payload.get(key))
        if message:
            return message
    message = _fill_number("包件件数", payload.get("package_count"), whole=True)
    if message:
        return message
    filled = any(_text(payload.get(key)) for key in ("size", "vessel_voyage", "package_count", *FILL_QTY, *FILL_TEXT))
    if not filled:
        return "没有可填写的字段"
    return ""


def _apply_material_fill(row, payload):
    if _text(payload.get("size")):
        length, width, height = _parse_size_text(payload.get("size"))
        if not _text(payload.get("length")):
            row.length = length
        if not _text(payload.get("width")):
            row.width = width
        if not _text(payload.get("height")):
            row.height = height
    for key in FILL_QTY:
        if _text(payload.get(key)):
            setattr(row, key, D(payload.get(key)))
    if _text(payload.get("package_count")):
        row.package_count = int(D(payload.get("package_count")))
    if _text(payload.get("vessel_voyage")):
        name, no = _split_vessel_voyage(payload.get("vessel_voyage"))
        row.vessel_name = name
        row.voyage_no = no
    for key in FILL_TEXT:
        if _text(payload.get(key)):
            setattr(row, key, _text(payload.get(key)))
    if _text(payload.get("receipt_no")) and not _text(row.receipt_no):
        row.receipt_no = _text(payload.get("receipt_no"))


def _mirror_material_fill(db, user, row):
    bump(row, user.employee_id)
    targets = []
    if row.receipt_item_id:
        stock = db.query(CustomsStock).filter(
            CustomsStock.receipt_item_id == row.receipt_item_id,
            CustomsStock.deleted_at.is_(None),
        ).first()
        item = db.query(WarehouseReceiptItem).filter(
            WarehouseReceiptItem.id == row.receipt_item_id,
            WarehouseReceiptItem.deleted_at.is_(None),
        ).first()
        targets = [target for target in (stock, item) if target]
    for target in targets:
        for key in FILL_MIRROR:
            if hasattr(target, key):
                setattr(target, key, getattr(row, key))
        bump(target, user.employee_id)


def _parse_material_fill(db, company_id, matrix, file_hash):
    from .importer import cell_text

    headers = [cell_text(cell) for cell in matrix[0]]
    cols = _header_map(headers, FILL_HEADERS)
    if "material_code" not in cols:
        raise BizError("表头不正确，请使用系统模板")
    parsed = []
    for index, raw in enumerate(matrix[1:], start=2):
        if not any(cell_text(cell) for cell in raw):
            continue
        payload = {}
        for key, col in cols.items():
            payload[key] = cell_text(raw[col]) if col < len(raw) else ""
        message = _validate_fill_payload(payload)
        matches = []
        if not message:
            matches = _match_materials(db, company_id, _text(payload.get("material_code")), _text(payload.get("receipt_no")))
            if not matches:
                message = "未找到该入仓单下的物料编号" if _text(payload.get("receipt_no")) else "未找到该物料编号"
        summary = " / ".join(part for part in (
            payload.get("material_code"), payload.get("origin_country"), payload.get("box_no"), payload.get("port_of_shipment"),
        ) if part)
        parsed.append({
            "row_no": index,
            "ok": not message,
            "summary": summary or payload.get("material_code") or "",
            "message": message or f"将更新 {len(matches)} 条",
            "payload": payload,
        })
    for row in parsed:
        if _text((row.get("payload") or {}).get("material_code")) in _fill_conflicts(parsed):
            row["ok"] = False
            row["message"] = "物料编号在文件中重复"
    errors = [{"row_no": row["row_no"], "field": "", "message": row["message"], "value": (row.get("payload") or {}).get("material_code")} for row in parsed if not row["ok"]]
    batch_error = ""
    if errors:
        batch_error = "存在错误数据，全部校验通过后才能导入。 " + "；".join(f"第{item['row_no']}行 {item['message']}" for item in errors[:8])
    return {"file_hash": file_hash, "mode": "update", "rows": parsed, "locks": [], "batch_error": batch_error, "errors": errors}


def _execute_material_fill(db, user, company_id, rows):
    conflicts = _fill_conflicts(rows)
    prepared = []
    errors = []
    for row in rows:
        payload = row.get("payload") or {}
        code = _text(payload.get("material_code"))
        message = "物料编号在文件中重复" if code in conflicts else _validate_fill_payload(payload)
        matches = []
        if not message:
            matches = _match_materials(db, company_id, code, _text(payload.get("receipt_no")))
            if not matches:
                message = "未找到该入仓单下的物料编号" if _text(payload.get("receipt_no")) else "未找到该物料编号"
        if message:
            errors.append({"row_no": row.get("row_no"), "message": message})
        else:
            prepared.append((payload, matches))
    if errors:
        raise BizError("存在错误数据，未写入数据库", data={"errors": errors})
    count = 0
    for payload, matches in prepared:
        for material in matches:
            _apply_material_fill(material, payload)
            _mirror_material_fill(db, user, material)
            count += 1
    op_log(db, user, company_id, "批量导入", "customs_material", "", {"rows": len(prepared), "updated": count})
    return {"success": count, "fail": 0, "errors": []}


RECEIPT_COLS = {
    "入仓单号": "receipt_no", "入仓日期": "receipt_date", "合同号": "contract_no", "箱单号": "packing_list_no",
    "物料大类": "material_category", "物料编号": "material_code", "中文名称": "material_name", "英文名称": "material_name_en",
    "规格": "specification", "单位": "unit", "数量": "quantity", "产地": "origin_country", "使用设备": "equipment",
    "箱号": "box_no", "集装箱号": "container_no", "提单号": "bill_no", "船名/航号": "vessel_voyage", "船名": "vessel_name", "航号": "voyage_no",
    "毛重": "gross_weight", "净重": "net_weight", "长": "length", "宽": "width", "高": "height", "体积": "volume",
    "PO单号": "po_no", "含税单价": "price", "特殊申报": "special_declare",
    "包件件数": "package_count", "询价名称": "inquiry_name", "询价型号": "inquiry_model", "询价数量": "inquiry_qty",
    "出发港": "port_of_shipment", "出发港口": "port_of_shipment", "目的港": "port_of_destination",
    "收货人": "consignee", "付款条款": "payment_terms", "HS Code": "hs_code", "HSCODE": "hs_code",
    "申报要素": "declaration_elements", "备注": "remark",
}
HS_COLS = {
    "HS Code": "hs_code", "HSCODE": "hs_code", "申报名称": "declaration_name", "产品名称": "product_name", "申报规格": "specification",
    "报关要素": "declaration_elements", "描述": "description", "状态": "status",
}


def _header_map(headers, mapping):
    found = {}
    for index, raw in enumerate(headers):
        key = str(raw or "").strip()
        if key in mapping:
            found[mapping[key]] = index
    return found


def parse_import(db, user, company_id, module, content: bytes, filename: str):
    from .importer import PARSE_FAIL, cell_text, read_matrix

    matrix = read_matrix(content, filename)
    if not matrix:
        raise BizError(PARSE_FAIL)
    file_hash = hashlib.sha256(content).hexdigest()
    if module == "customs-material-fill":
        return _parse_material_fill(db, company_id, matrix, file_hash)
    headers = [cell_text(cell) for cell in matrix[0]]
    mapping = RECEIPT_COLS if module == "warehouse-receipt" else HS_COLS
    cols = _header_map(headers, mapping)
    required = ("material_code", "material_name", "quantity") if module == "warehouse-receipt" else ("hs_code", "declaration_name")
    if any(key not in cols for key in required):
        raise BizError("表头不正确，请使用系统模板")
    rows = []
    errors = []
    seen_hs = set()
    for index, raw in enumerate(matrix[1:], start=2):
        if not any(cell_text(cell) for cell in raw):
            continue
        payload = {}
        for key, col in cols.items():
            payload[key] = cell_text(raw[col]) if col < len(raw) else ""
        if payload.get("vessel_voyage"):
            name, no = _split_vessel_voyage(payload.get("vessel_voyage"))
            payload["vessel_name"] = name
            payload["voyage_no"] = no
        message = ""
        if module == "warehouse-receipt":
            if not payload.get("material_code"):
                message = "物料编号不能为空"
            elif not payload.get("quantity") or D(payload.get("quantity") or 0) <= 0:
                message = "数量必须大于 0"
            else:
                try:
                    D(payload.get("quantity"))
                except Exception:
                    message = "数量格式不正确"
        else:
            pair = (payload.get("hs_code"), payload.get("declaration_name"))
            if not pair[0] or not pair[1]:
                message = "HS Code 和申报名称不能为空"
            elif pair in seen_hs:
                message = "文件内 HS Code 重复"
            else:
                seen_hs.add(pair)
                dup = q(db, HsCodeLibrary, company_id).filter(HsCodeLibrary.hs_code == pair[0], HsCodeLibrary.declaration_name == pair[1]).first()
                if dup:
                    message = "HS Code 已存在"
        if message:
            errors.append({"row_no": index, "field": "", "message": message, "value": payload.get("material_code") or payload.get("hs_code")})
        summary = payload.get("material_name") or payload.get("declaration_name") or payload.get("material_code") or payload.get("hs_code")
        rows.append({"row_no": index, "ok": not message, "summary": summary, "message": message or "可导入", "payload": payload})
    batch_error = ""
    if errors:
        batch_error = "存在错误数据，全部校验通过后才能导入。 " + "；".join(f"第{item['row_no']}行 {item['message']}" for item in errors[:8])
    return {"file_hash": file_hash, "mode": "create", "rows": rows, "locks": [], "batch_error": batch_error, "errors": errors}


def execute_import(db, user, company_id, module, payload: dict):
    rows = payload.get("rows") or []
    bad = [row for row in rows if not row.get("ok")]
    if bad:
        raise BizError("存在错误数据，未写入数据库", data={"errors": [{"row_no": row.get("row_no"), "message": row.get("message")} for row in bad]})
    if not rows:
        raise BizError("没有可导入的数据")
    if module == "customs-material-fill":
        return _execute_material_fill(db, user, company_id, rows)
    if module == "hs-code":
        count = 0
        for row in rows:
            save_hs(db, user, company_id, row.get("payload") or {}, None)
            count += 1
        op_log(db, user, company_id, "导入", "hs_code_library", "", {"count": count})
        return {"success": count, "fail": 0, "errors": []}
    grouped = {}
    for row in rows:
        data = row.get("payload") or {}
        code = _text(data.get("receipt_no")) or "__AUTO__"
        grouped.setdefault(code, []).append(data)
    count = 0
    for code, items in grouped.items():
        first = items[0]
        body = {
            "receipt_no": "" if code == "__AUTO__" else code,
            "receipt_date": first.get("receipt_date"),
            "contract_no": first.get("contract_no"),
            "packing_list_no": first.get("packing_list_no"),
            "items": items,
        }
        save_receipt(db, user, company_id, body, None)
        count += 1
    op_log(db, user, company_id, "导入", "warehouse_receipt", "", {"receipts": count, "items": len(rows)})
    return {"success": len(rows), "fail": 0, "errors": []}
