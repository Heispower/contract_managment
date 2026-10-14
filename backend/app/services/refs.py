"""删除被挡住时，列出仍在引用的下游单据。"""
from ..errors import BizError
from ..models import (
    CheckBill,
    Contract,
    ContractItem,
    ContractOrder,
    Goods,
    Invoice,
    InvoiceItem,
    OrderItem,
    OtherBill,
    SettleBill,
    Stock,
    TransferBill,
    Warehouse,
    WmsBill,
    WmsItem,
)
from .util import MSG_REF, q


def raise_ref(lines):
    cleaned = []
    seen = set()
    for line in lines:
        text = str(line or "").strip()
        if text and text not in seen:
            seen.add(text)
            cleaned.append(text)
    if cleaned:
        raise BizError(MSG_REF, data={"refs": cleaned})


def contract_text(row: Contract):
    if row.nature == "supplement":
        kind = "补充协议"
    elif row.direction == "sale":
        kind = "销售合同"
    else:
        kind = "采购合同"
    return f"{kind} {row.contract_code}"


def order_text(row: ContractOrder):
    kind = "销售订单" if row.direction == "sale" else "采购订单"
    return f"{kind} {row.order_code}"


def wms_text(row: WmsBill):
    kind = "采购入库" if row.type == "inbound" else "销售出库"
    return f"{kind} {row.bill_code}"


def settle_text(row: SettleBill):
    kind = "收款单" if row.direction == "receipt" else "付款单"
    return f"{kind} {row.bill_code}"


def invoice_text(row: Invoice):
    kind = "销项发票" if row.direction == "output" else "进项发票"
    return f"{kind} {row.invoice_no or row.bill_code}"


def other_text(row: OtherBill):
    kind = "其他收入" if row.direction == "income" else "其他支出"
    return f"{kind} {row.bill_code}"


def refuse_contract(db, company_id, contract_id):
    lines = [order_text(row) for row in q(db, ContractOrder, company_id).filter(ContractOrder.contract_id == contract_id)]
    lines += [wms_text(row) for row in q(db, WmsBill, company_id).filter(WmsBill.contract_id == contract_id)]
    lines += [settle_text(row) for row in q(db, SettleBill, company_id).filter(SettleBill.contract_id == contract_id)]
    lines += [invoice_text(row) for row in q(db, Invoice, company_id).filter(Invoice.contract_id == contract_id)]
    raise_ref(lines)


def refuse_stage(db, stage_id):
    rows = db.query(SettleBill).filter(SettleBill.stage_id == stage_id, SettleBill.deleted_at.is_(None)).all()
    raise_ref([settle_text(row) for row in rows])


def refuse_party(db, company_id, party_id):
    lines = [contract_text(row) for row in q(db, Contract, company_id).filter(Contract.party_id == party_id)]
    lines += [order_text(row) for row in q(db, ContractOrder, company_id).filter(ContractOrder.party_id == party_id)]
    lines += [settle_text(row) for row in q(db, SettleBill, company_id).filter(SettleBill.party_id == party_id)]
    lines += [invoice_text(row) for row in q(db, Invoice, company_id).filter(Invoice.party_id == party_id)]
    raise_ref(lines)


def refuse_project(db, company_id, project_id):
    rows = q(db, Contract, company_id).filter(Contract.project_id == project_id).all()
    raise_ref([contract_text(row) for row in rows])


def refuse_plan(db, company_id, material_code):
    rows = (
        db.query(Contract)
        .join(ContractItem, ContractItem.contract_id == Contract.id)
        .filter(
            Contract.company_id == company_id,
            Contract.direction == "purchase",
            Contract.deleted_at.is_(None),
            ContractItem.deleted_at.is_(None),
            ContractItem.material_code == material_code,
        )
        .all()
    )
    raise_ref([contract_text(row) for row in rows])


def refuse_account(db, company_id, name):
    lines = [settle_text(row) for row in q(db, SettleBill, company_id).filter(SettleBill.account_name == name)]
    lines += [other_text(row) for row in q(db, OtherBill, company_id).filter(OtherBill.account_name == name)]
    raise_ref(lines)


def refuse_warehouse(db, company_id, warehouse_id):
    lines = []
    stocks = db.query(Stock).filter(Stock.warehouse_id == warehouse_id, Stock.deleted_at.is_(None)).all()
    wh = db.get(Warehouse, warehouse_id)
    place = wh.name if wh else ""
    lines += [f"库存余额 {row.material_code} {place}".strip() for row in stocks]
    lines += [wms_text(row) for row in q(db, WmsBill, company_id).filter(WmsBill.warehouse_id == warehouse_id)]
    lines += [f"调拨记录 {row.bill_code}" for row in q(db, TransferBill, company_id).filter((TransferBill.warehouse_out == warehouse_id) | (TransferBill.warehouse_in == warehouse_id))]
    lines += [f"盘点记录 {row.bill_code}" for row in q(db, CheckBill, company_id).filter(CheckBill.warehouse_id == warehouse_id)]
    raise_ref(lines)


def refuse_goods(db, company_id, code):
    contracts = (
        db.query(Contract)
        .join(ContractItem, ContractItem.contract_id == Contract.id)
        .filter(
            Contract.company_id == company_id,
            Contract.deleted_at.is_(None),
            ContractItem.deleted_at.is_(None),
            ContractItem.material_code == code,
        )
        .all()
    )
    orders = (
        db.query(ContractOrder)
        .join(OrderItem, OrderItem.order_id == ContractOrder.id)
        .filter(
            ContractOrder.company_id == company_id,
            ContractOrder.deleted_at.is_(None),
            OrderItem.deleted_at.is_(None),
            OrderItem.material_code == code,
        )
        .all()
    )
    invoices = (
        db.query(Invoice)
        .join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
        .filter(
            Invoice.company_id == company_id,
            Invoice.deleted_at.is_(None),
            InvoiceItem.deleted_at.is_(None),
            InvoiceItem.material_code == code,
        )
        .all()
    )
    bills = (
        db.query(WmsBill)
        .join(WmsItem, WmsItem.bill_id == WmsBill.id)
        .filter(
            WmsBill.company_id == company_id,
            WmsBill.deleted_at.is_(None),
            WmsItem.deleted_at.is_(None),
            WmsItem.material_code == code,
        )
        .all()
    )
    stocks = db.query(Stock).filter(Stock.company_id == company_id, Stock.material_code == code, Stock.deleted_at.is_(None), Stock.qty != "0").all()
    lines = [contract_text(row) for row in contracts]
    lines += [order_text(row) for row in orders]
    lines += [invoice_text(row) for row in invoices]
    lines += [wms_text(row) for row in bills]
    lines += [f"库存余额 {row.material_code}" for row in stocks]
    raise_ref(lines)


def refuse_category(db, company_id, code):
    rows = q(db, Goods, company_id).filter(Goods.category_code == code).all()
    raise_ref([f"商品 {row.material_code} {row.name}".strip() for row in rows])


def refuse_user(db, employee_id):
    lines = []
    contracts = db.query(Contract).filter(Contract.deleted_at.is_(None), (Contract.owner_id == employee_id) | (Contract.created_by == employee_id)).all()
    lines += [contract_text(row) for row in contracts]
    orders = db.query(ContractOrder).filter(ContractOrder.deleted_at.is_(None), ContractOrder.owner_id == employee_id).all()
    lines += [order_text(row) for row in orders]
    settles = db.query(SettleBill).filter(SettleBill.deleted_at.is_(None), SettleBill.created_by == employee_id).all()
    lines += [settle_text(row) for row in settles]
    invoices = db.query(Invoice).filter(Invoice.deleted_at.is_(None), Invoice.created_by == employee_id).all()
    lines += [invoice_text(row) for row in invoices]
    bills = db.query(WmsBill).filter(WmsBill.deleted_at.is_(None), WmsBill.created_by == employee_id).all()
    lines += [wms_text(row) for row in bills]
    raise_ref(lines)
