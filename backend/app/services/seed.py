"""系统种子与演示业务数据。重复初始化会先清掉演示业务再重建。"""
from decimal import Decimal

from ..config import DEPLOY_MODE
from ..errors import BizError
from ..models import (
    Company,
    ContractStage,
    ContractType,
    CustomsMaterial,
    ExchangeRate,
    FundAccount,
    Goods,
    GoodsCategory,
    HsCodeLibrary,
    OpLog,
    Party,
    PartyContact,
    PurchasePlan,
    SysConfig,
    SysDept,
    SysPost,
    SysRole,
    SysUser,
    SysUserCompany,
    Warehouse,
    WarehouseReceipt,
    WmsBill,
    now,
)
from ..security import hash_password
from .ops import save_contract, save_order, save_settle_many, save_wms
from .util import op_log


BUSINESS_TABLES = [
    "customs_element_item",
    "customs_element",
    "customs_clearance_pl",
    "customs_clearance_item",
    "customs_clearance",
    "customs_invoice_link",
    "customs_invoice_item",
    "customs_invoice",
    "customs_material",
    "customs_stock",
    "warehouse_receipt_item",
    "warehouse_receipt",
    "hs_code_library",
    "exchange_rate",
    "invoice_item",
    "invoice",
    "settle_bill",
    "other_bill",
    "wms_item",
    "wms_bill",
    "stock",
    "transfer_bill",
    "check_bill",
    "order_item",
    "contract_order",
    "contract_stage",
    "contract_item",
    "contract",
    "purchase_plan",
    "reminder_record",
    "party_contact",
    "party",
    "project",
    "goods",
    "goods_category",
    "import_idem",
]


def _user(employee_id, login_name, name, password, **flags):
    row = SysUser(
        employee_id=employee_id,
        login_name=login_name,
        name=name,
        password_hash=hash_password(password),
        status="启用",
        is_super_admin=flags.get("is_super_admin", False),
        can_import_overwrite=flags.get("can_import_overwrite", False),
        failed_login_count=0,
        auth_version=1,
        must_change_password=flags.get("must_change_password", False),
        role_text=flags.get("role_text"),
        version=1,
        created_by="system",
        updated_by="system",
        created_at=now(),
        updated_at=now(),
    )
    return row


class SeedUser:
    def __init__(self, employee_id):
        self.employee_id = employee_id


def seed_system(db):
    if db.query(SysUser).filter(SysUser.login_name == "admin").first():
        return
    star = Company(name="星河科技", short_name="星河科技", tax_no="91310000STAR", address="上海市浦东新区", version=1, created_by="system", updated_by="system", created_at=now(), updated_at=now())
    jiang = Company(name="江南建设", short_name="江南建设", tax_no="91320000JIANG", address="南京市建邺区", version=1, created_by="system", updated_by="system", created_at=now(), updated_at=now())
    db.add_all([star, jiang])
    db.flush()
    admin = _user(
        "admin",
        "admin",
        "系统管理员",
        "123456",
        is_super_admin=True,
        can_import_overwrite=True,
        must_change_password=DEPLOY_MODE == "formal",
        role_text="管理员",
    )
    zhang = _user("E001", "zhang", "张三", "123456", role_text="业务员")
    li = _user("E002", "li", "李四", "123456", role_text="业务员")
    db.add_all([admin, zhang, li])
    db.flush()
    db.add_all([
        SysUserCompany(employee_id="E001", company_id=star.id, is_default=True),
        SysUserCompany(employee_id="E002", company_id=jiang.id, is_default=True),
    ])
    for company, user_id in ((star, "admin"), (jiang, "admin")):
        db.add(Warehouse(company_id=company.id, code="MAIN", name="主仓", status="启用", version=1, created_by=user_id, updated_by=user_id, created_at=now(), updated_at=now()))
        db.add(FundAccount(company_id=company.id, code="BASE", name="基本户", account_no="622200001", status="启用", version=1, created_by=user_id, updated_by=user_id, created_at=now(), updated_at=now()))
        db.add(ContractType(company_id=company.id, code="CG", name="材料采购", status="启用", version=1, created_by=user_id, updated_by=user_id, created_at=now(), updated_at=now()))
        db.add(ContractType(company_id=company.id, code="XS", name="产品销售", status="启用", version=1, created_by=user_id, updated_by=user_id, created_at=now(), updated_at=now()))
        db.add(GoodsCategory(company_id=company.id, code="STEEL", name="钢材", version=1, created_by=user_id, updated_by=user_id, created_at=now(), updated_at=now()))
        db.add(SysRole(company_id=company.id, code="SALES", name="业务员", version=1, created_by=user_id, updated_by=user_id, created_at=now(), updated_at=now()))
        db.add(SysDept(company_id=company.id, code="BIZ", name="业务部", version=1, created_by=user_id, updated_by=user_id, created_at=now(), updated_at=now()))
        db.add(SysPost(company_id=company.id, code="STAFF", name="专员", version=1, created_by=user_id, updated_by=user_id, created_at=now(), updated_at=now()))
    db.add_all([
        SysConfig(config_name="密码最小长度", config_value="6", version=1, created_by="system", updated_by="system", created_at=now(), updated_at=now()),
        SysConfig(config_name="登录失败锁定次数", config_value="5", version=1, created_by="system", updated_by="system", created_at=now(), updated_at=now()),
        SysConfig(config_name="登录锁定时长（分钟）", config_value="30", version=1, created_by="system", updated_by="system", created_at=now(), updated_at=now()),
    ])
    db.add(OpLog(operator="system", company_id=star.id, action="初始化", biz_type="system", biz_id="0", detail="初始化演示数据", ip="127.0.0.1", created_at=now()))
    db.flush()
    seed_demo_business(db)


def clear_business(db):
    from sqlalchemy import text

    for name in BUSINESS_TABLES:
        db.execute(text(f"DELETE FROM {name}"))
    db.flush()


# 业务单据、基础资料、组织、日志。安全配置和当前登录账号不在这里。
WIPE_TABLES = BUSINESS_TABLES + [
    "company_contact",
    "fund_account",
    "contract_type",
    "export_profile",
    "warehouse",
    "sys_role",
    "sys_dept",
    "sys_post",
    "login_log",
    "op_log",
]


def wipe_all_data(db, keep_employee_id: str, keep_company_id: int) -> int:
    """硬删除全部业务数据，包括已软删除、仍占用编号的记录。

    保留当前登录账号、当前公司和安全配置，否则清空后无法登录。
    """
    import shutil
    from sqlalchemy import text

    from ..config import UPLOAD_DIR
    from ..models import Company, OpLog, SysUserCompany

    company = db.get(Company, keep_company_id)
    if company is None:
        raise BizError("没有可访问的公司")
    removed = 0
    for name in WIPE_TABLES:
        result = db.execute(text(f"DELETE FROM {name}"))
        removed += int(result.rowcount or 0)
    result = db.execute(text("DELETE FROM company WHERE id != :id"), {"id": keep_company_id})
    removed += int(result.rowcount or 0)
    result = db.execute(
        text("DELETE FROM sys_user WHERE employee_id != :employee_id"),
        {"employee_id": keep_employee_id},
    )
    removed += int(result.rowcount or 0)
    result = db.execute(text("DELETE FROM sys_user_company"))
    removed += int(result.rowcount or 0)
    if company.deleted_at:
        company.deleted_at = None
    db.add(SysUserCompany(employee_id=keep_employee_id, company_id=keep_company_id, is_default=True))
    sequence = db.execute(text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'")).first()
    if sequence:
        names = ", ".join(f"'{name}'" for name in WIPE_TABLES)
        db.execute(text(f"DELETE FROM sqlite_sequence WHERE name IN ({names})"))
    db.add(OpLog(
        operator=keep_employee_id,
        company_id=keep_company_id,
        action="清空数据",
        biz_type="system",
        biz_id="0",
        detail="清空全部业务数据",
        ip="127.0.0.1",
        created_at=now(),
    ))
    db.flush()
    if UPLOAD_DIR.exists():
        for path in UPLOAD_DIR.iterdir():
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
    return removed


def seed_demo_business(db):
    star = db.query(Company).filter(Company.short_name == "星河科技").first()
    jiang = db.query(Company).filter(Company.short_name == "江南建设").first()
    admin = SeedUser("admin")
    _company_demo(db, star, admin, "E001", "S001", "南方钢材", "C001", "华东机电", "CG-2026-001", "XS-2026-001")
    _company_demo(db, jiang, admin, "E002", "S009", "金陵水泥", "C009", "西湖材料", "CG-2026-001", "XS-2026-001", small=True)
    seed_customs_demo(db)
    op_log(db, admin, star.id, "初始化", "system", "demo", "初始化演示数据")


def _company_demo(db, company, admin, owner_id, supplier_code, supplier_name, customer_code, customer_name, cg_code, xs_code, small=False):
    supplier = Party(
        company_id=company.id, code=supplier_code, name=supplier_name, type="supplier",
        tax_no="91310000SUP", default_tax_rate=Decimal("13"), status="启用",
        supplier_category="原材料", invoice_title=supplier_name, address="工业路 1 号",
        version=1, created_by="admin", updated_by="admin", created_at=now(), updated_at=now(),
    )
    customer = Party(
        company_id=company.id, code=customer_code, name=customer_name, type="customer",
        tax_no="91310000CUS", default_tax_rate=Decimal("13"), status="启用",
        salesman_id=owner_id, invoice_title=customer_name, address="商务路 8 号",
        version=1, created_by="admin", updated_by="admin", created_at=now(), updated_at=now(),
    )
    db.add_all([supplier, customer])
    db.flush()
    db.add(PartyContact(company_id=company.id, party_id=customer.id, name="王敏", phone="13800001111", is_default=True, version=1, created_by="admin", updated_by="admin", created_at=now(), updated_at=now()))
    goods = Goods(
        company_id=company.id, material_code="M001", name="热轧钢板", spec="10mm", unit="吨",
        category_code="STEEL", price=Decimal("5000.00"),
        version=1, created_by="admin", updated_by="admin", created_at=now(), updated_at=now(),
    )
    goods2 = Goods(
        company_id=company.id, material_code="M002", name="高强螺栓", spec="M16", unit="件",
        category_code="STEEL", price=Decimal("2.00"),
        version=1, created_by="admin", updated_by="admin", created_at=now(), updated_at=now(),
    )
    db.add_all([goods, goods2])
    plan_qty = Decimal("20") if small else Decimal("100")
    db.add(PurchasePlan(
        company_id=company.id, plan_month="2026-03", purchase_seq="1", material_code="M001",
        plan_no="PL-001", category="钢材", name_cn="热轧钢板", spec="10mm", unit="吨",
        qty=plan_qty, purpose="生产", version=1, created_by="admin", updated_by="admin", created_at=now(), updated_at=now(),
    ))
    db.flush()
    qty = "4" if small else "10"
    price = "4800" if small else "5000"
    purchase = save_contract(db, admin, company.id, {
        "contract_code": cg_code,
        "name": "钢板采购合同",
        "direction": "purchase",
        "nature": "main",
        "type_name": "材料采购",
        "party_id": supplier.id,
        "owner_id": owner_id,
        "status": "已签订",
        "pricing": "fixed",
        "tax_rate": "13",
        "sign_date": "2026-03-01",
        "start_date": "2026-03-01",
        "end_date": "2026-12-31",
        "content": "采购热轧钢板",
        "items": [{
            "material_code": "M001", "name_cn": "热轧钢板", "spec": "10mm", "unit": "吨",
            "qty": qty, "price": price, "plan_no": "PL-001", "category": "钢材",
        }],
    })
    sale_price = "6200" if small else "8000"
    sale = save_contract(db, admin, company.id, {
        "contract_code": xs_code,
        "name": "钢板销售合同",
        "direction": "sale",
        "nature": "main",
        "type_name": "产品销售",
        "party_id": customer.id,
        "owner_id": owner_id,
        "status": "已签订",
        "pricing": "fixed",
        "tax_rate": "13",
        "sign_date": "2026-03-02",
        "start_date": "2026-03-02",
        "end_date": "2026-06-30",
        "items": [{
            "material_code": "M001", "name_cn": "热轧钢板", "spec": "10mm", "unit": "吨",
            "qty": qty, "price": sale_price,
        }],
    })
    if small:
        return
    save_order(db, admin, company.id, {
        "contract_id": purchase.id,
        "direction": "purchase",
        "items": [{"material_code": "M001", "name_cn": "热轧钢板", "spec": "10mm", "unit": "吨", "qty": qty, "price": price}],
    })
    warehouse = db.query(Warehouse).filter(Warehouse.company_id == company.id, Warehouse.name == "主仓").one()
    save_wms(db, admin, company.id, {
        "type": "inbound",
        "contract_id": purchase.id,
        "warehouse_id": warehouse.id,
        "bill_date": "2026-03-10",
        "items": [{"material_code": "M001", "name_cn": "热轧钢板", "spec": "10mm", "unit": "吨", "qty": "4", "price": price}],
    })
    stage = db.query(ContractStage).filter(ContractStage.contract_id == purchase.id, ContractStage.seq == 1, ContractStage.deleted_at.is_(None)).one()
    save_settle_many(db, admin, company.id, {
        "direction": "payment",
        "contract_id": purchase.id,
        "party_id": supplier.id,
        "bill_code": "FK-DEMO-001",
        "bill_date": "2026-03-05",
        "account_name": "基本户",
        "lines": [{"stage_id": stage.id, "amount": str(stage.plan_amount)}],
    })
    _ = sale


def seed_customs_demo(db):
    """补齐报关物料、HS、汇率，让物料清单 → 报关发票 → 清关发票 → 报关要素可整链演示。"""
    star = db.query(Company).filter(Company.short_name == "星河科技").first()
    if not star:
        return
    admin = SeedUser("admin")
    _seed_hs_and_rates(db, admin, star.id)
    _complete_wms_materials(db, star.id)
    if db.query(WarehouseReceipt).filter(
        WarehouseReceipt.company_id == star.id,
        WarehouseReceipt.receipt_no == "RK-BG-001",
        WarehouseReceipt.deleted_at.is_(None),
    ).first():
        return
    if db.query(WmsBill).filter(
        WmsBill.company_id == star.id,
        WmsBill.bill_code == "RK-BG-001",
        WmsBill.deleted_at.is_(None),
    ).first():
        return
    from .customs import generate_clearance, generate_element, generate_invoice
    from .ops import save_contract, save_wms
    from .util import q

    supplier = db.query(Party).filter(Party.company_id == star.id, Party.code == "S001").first()
    supplier_id = supplier.id if supplier else None
    supplier_name = supplier.name if supplier else "南方钢材"

    warehouse = db.query(Warehouse).filter(Warehouse.company_id == star.id, Warehouse.name == "主仓").one()
    _seed_bg_inbound(db, admin, star.id, supplier_id, warehouse.id, save_contract, save_wms, "HT-BG-2026-001", "轴承采购合同", "RK-BG-001", "2026-10-01", "PL-BG-001", "轴承到货，含两箱可合并及一箱特殊申报", [
        _bg_item("BG-B01", "深沟球轴承", "Deep groove bearing", "轴承", "6205-2RS", "套", "20", "中国", "包装机", {
            "box_no": "BOX-A01", "container_no": "TCLU1234567", "bill_no": "COSU12345678",
            "vessel_voyage": "EVER GIVEN/V026E", "gw": "12", "nw": "10", "l": "30", "w": "20", "h": "15",
            "vol": "0.009", "po": "PO-BG-001", "price": "85",
        }),
        _bg_item("BG-B02", "深沟球轴承", "Deep groove bearing", "轴承", "6205-2RS", "套", "15", "中国", "包装机", {
            "box_no": "BOX-A02", "container_no": "TCLU1234567", "bill_no": "COSU12345678",
            "vessel_voyage": "EVER GIVEN/V026E", "gw": "9", "nw": "7.5", "l": "30", "w": "20", "h": "15",
            "vol": "0.009", "po": "PO-BG-001", "price": "85",
        }),
        _bg_item("BG-B03", "角接触轴承", "Angular contact bearing", "轴承", "7205C", "套", "8", "日本", "包装机", {
            "box_no": "BOX-A03", "container_no": "TCLU1234567", "bill_no": "COSU12345678",
            "vessel_voyage": "EVER GIVEN/V026E", "gw": "6", "nw": "5", "l": "28", "w": "18", "h": "14",
            "vol": "0.007", "po": "PO-BG-001", "price": "210", "special": True,
        }),
    ])
    _seed_bg_inbound(db, admin, star.id, supplier_id, warehouse.id, save_contract, save_wms, "HT-BG-2026-002", "钢材采购合同", "RK-BG-002", "2026-10-05", "PL-BG-002", "钢材可合并，密封件单独成行；演示已生成报关/清关/要素", [
        _bg_item("BG-S01", "热轧钢板", "Hot rolled plate", "钢材", "10mm Q235", "吨", "6", "中国", "产线A", {
            "box_no": "BOX-S01", "container_no": "TCLU7654321", "bill_no": "COSU87654321",
            "vessel_voyage": "COSCO STAR/V12", "gw": "6200", "nw": "6000", "l": "600", "w": "200", "h": "10",
            "vol": "1.2", "po": "PO-BG-002", "price": "4800",
        }),
        _bg_item("BG-S02", "冷轧钢板", "Cold rolled plate", "钢材", "1.2mm SPCC", "吨", "4", "中国", "产线A", {
            "box_no": "BOX-S02", "container_no": "TCLU7654321", "bill_no": "COSU87654321",
            "vessel_voyage": "COSCO STAR/V12", "gw": "4200", "nw": "4000", "l": "500", "w": "180", "h": "8",
            "vol": "0.72", "po": "PO-BG-002", "price": "5200",
        }),
        _bg_item("BG-F01", "骨架油封", "Oil seal", "密封件", "50*70*10", "件", "120", "德国", "减速机", {
            "box_no": "BOX-F01", "container_no": "TCLU7654321", "bill_no": "COSU87654321",
            "vessel_voyage": "COSCO STAR/V12", "gw": "18", "nw": "15", "l": "40", "w": "30", "h": "20",
            "vol": "0.024", "po": "PO-BG-002", "price": "12.5",
        }),
    ])
    _seed_bg_inbound(db, admin, star.id, supplier_id, warehouse.id, save_contract, save_wms, "HT-BG-2026-003", "机电采购合同", "RK-BG-003", "2026-10-08", "PL-BG-003", "电机与减速机分开展示不同大类", [
        _bg_item("BG-M01", "三相异步电机", "Three-phase motor", "电机", "YE2-132M-4", "台", "2", "中国", "输送线", {
            "box_no": "BOX-M01", "container_no": "MSKU8888888", "bill_no": "MSCU99887766",
            "vessel_voyage": "MSC OSCAR/V08W", "gw": "95", "nw": "88", "l": "80", "w": "50", "h": "45",
            "vol": "0.18", "po": "PO-BG-003", "price": "1850",
        }),
        _bg_item("BG-M02", "蜗轮减速机", "Worm gearbox", "减速机", "NMRV90", "台", "3", "意大利", "输送线", {
            "box_no": "BOX-M02", "container_no": "MSKU8888888", "bill_no": "MSCU99887766",
            "vessel_voyage": "MSC OSCAR/V08W", "gw": "72", "nw": "65", "l": "60", "w": "40", "h": "35",
            "vol": "0.084", "po": "PO-BG-003", "price": "960",
        }),
    ])

    ready = q(db, CustomsMaterial, star.id).filter(CustomsMaterial.contract_no == "HT-BG-2026-002").all()
    ids = [row.id for row in ready]
    invoice = generate_invoice(db, admin, star.id, {"ids": ids, "invoice_no": "BG-DEMO-001", "invoice_date": "2026-10-06"})
    generate_clearance(db, admin, star.id, {
        "ids": ids, "invoice_no": "QG-DEMO-001", "invoice_date": "2026-10-06", "vessel_voyage": "COSCO STAR/V12",
    })
    generate_element(db, admin, star.id, {"invoice_id": invoice.id})


def _seed_bg_inbound(db, admin, company_id, supplier_id, warehouse_id, save_contract, save_wms, contract_no, name, bill_code, bill_date, packing, remark, items):
    from .util import stamp_new

    for item in items:
        plan = db.query(PurchasePlan).filter(
            PurchasePlan.company_id == company_id,
            PurchasePlan.material_code == item["material_code"],
            PurchasePlan.deleted_at.is_(None),
        ).first()
        need = Decimal(str(item["quantity"]))
        if plan is None:
            plan = PurchasePlan(
                plan_month=bill_date[:7],
                material_code=item["material_code"],
                name_cn=item["material_name"],
                spec=item.get("specification") or "",
                unit=item.get("unit") or "",
                qty=need,
                purpose="报关演示",
            )
            stamp_new(plan, admin, company_id)
            db.add(plan)
        elif plan.qty < need:
            plan.qty = need
    db.flush()
    contract = save_contract(db, admin, company_id, {
        "contract_code": contract_no,
        "name": name,
        "direction": "purchase",
        "nature": "main",
        "type_name": "材料采购",
        "party_id": supplier_id,
        "owner_id": "admin",
        "status": "已签订",
        "pricing": "fixed",
        "tax_rate": "13",
        "sign_date": bill_date,
        "content": remark,
        "items": [{
            "material_code": item["material_code"],
            "name_cn": item["material_name"],
            "name_en": item.get("material_name_en") or "",
            "spec": item.get("specification") or "",
            "unit": item.get("unit") or "",
            "qty": item["quantity"],
            "price": item.get("price") or "0",
            "category": item.get("equipment") or "",
        } for item in items],
    })
    bill = save_wms(db, admin, company_id, {
        "type": "inbound",
        "bill_code": bill_code,
        "bill_date": bill_date,
        "contract_id": contract.id,
        "warehouse_id": warehouse_id,
        "remark": remark,
        "items": [{
            "material_code": item["material_code"],
            "name_cn": item["material_name"],
            "spec": item.get("specification") or "",
            "unit": item.get("unit") or "",
            "qty": item["quantity"],
            "price": item.get("price") or "0",
            "category": item.get("equipment") or "",
        } for item in items],
    })
    mats = {
        row.material_code: row
        for row in db.query(CustomsMaterial).filter(
            CustomsMaterial.company_id == company_id,
            CustomsMaterial.wms_bill_id == bill.id,
            CustomsMaterial.deleted_at.is_(None),
        ).all()
    }
    for item in items:
        row = mats[item["material_code"]]
        row.packing_list_no = packing
        row.material_category = item.get("material_category") or row.material_category
        row.material_name_en = item.get("material_name_en") or ""
        row.origin_country = item.get("origin_country") or ""
        row.box_no = item.get("box_no") or ""
        row.container_no = item.get("container_no") or ""
        row.bill_no = item.get("bill_no") or ""
        voyage = item.get("vessel_voyage") or ""
        if "/" in voyage:
            row.vessel_name, row.voyage_no = [part.strip() for part in voyage.split("/", 1)]
        row.gross_weight = Decimal(str(item.get("gross_weight") or 0))
        row.net_weight = Decimal(str(item.get("net_weight") or 0))
        row.length = Decimal(str(item.get("length") or 0))
        row.width = Decimal(str(item.get("width") or 0))
        row.height = Decimal(str(item.get("height") or 0))
        row.volume = Decimal(str(item.get("volume") or 0))
        row.po_no = item.get("po_no") or ""
        row.special_declare = bool(item.get("special_declare"))


def _bg_item(code, name, name_en, category, spec, unit, qty, origin, equipment, extra):
    return {
        "material_code": code,
        "material_name": name,
        "material_name_en": name_en,
        "material_category": category,
        "specification": spec,
        "unit": unit,
        "quantity": qty,
        "origin_country": origin,
        "equipment": equipment,
        "box_no": extra.get("box_no"),
        "container_no": extra.get("container_no"),
        "bill_no": extra.get("bill_no"),
        "vessel_voyage": extra.get("vessel_voyage"),
        "gross_weight": extra.get("gw"),
        "net_weight": extra.get("nw"),
        "length": extra.get("l"),
        "width": extra.get("w"),
        "height": extra.get("h"),
        "volume": extra.get("vol"),
        "po_no": extra.get("po"),
        "price": extra.get("price"),
        "special_declare": extra.get("special", False),
    }


def _seed_hs_and_rates(db, user, company_id):
    from .customs import save_hs, save_rate

    catalog = [
        ("84821000", "轴承", "滚动轴承", "品牌类型;结构类型;轴承型号"),
        ("72104900", "钢材", "热轧/冷轧钢板", "材质;规格;加工方法"),
        ("40169300", "密封件", "硫化橡胶制品", "材质;用途;规格"),
        ("85015200", "电机", "多相交流电动机", "功率;电压;用途"),
        ("84834090", "减速机", "齿轮及齿轮传动", "型号;速比;用途"),
    ]
    for code, name, spec, elements in catalog:
        exists = db.query(HsCodeLibrary).filter(
            HsCodeLibrary.company_id == company_id,
            HsCodeLibrary.hs_code == code,
            HsCodeLibrary.declaration_name == name,
            HsCodeLibrary.deleted_at.is_(None),
        ).first()
        if exists:
            continue
        save_hs(db, user, company_id, {
            "hs_code": code, "declaration_name": name, "specification": spec, "declaration_elements": elements,
        }, None)
    for year, month, rate in ((2026, 10, "7.12"), (2026, 3, "7.18")):
        exists = db.query(ExchangeRate).filter(
            ExchangeRate.company_id == company_id,
            ExchangeRate.year == year,
            ExchangeRate.month == month,
            ExchangeRate.currency == "USD",
            ExchangeRate.deleted_at.is_(None),
        ).first()
        if exists:
            continue
        save_rate(db, user, company_id, {"year": year, "month": month, "currency": "USD", "rate": rate}, None)


def _complete_wms_materials(db, company_id):
    from .customs import missing_fields

    rows = db.query(CustomsMaterial).filter(
        CustomsMaterial.company_id == company_id,
        CustomsMaterial.wms_bill_id.isnot(None),
        CustomsMaterial.deleted_at.is_(None),
    ).all()
    for row in rows:
        if not missing_fields(row):
            continue
        row.packing_list_no = row.packing_list_no or "PL-WMS-001"
        row.origin_country = row.origin_country or "中国"
        row.equipment = row.equipment or row.material_category or "产线A"
        row.material_category = row.material_category or "钢材"
        row.container_no = row.container_no or "TCLU0001001"
        row.bill_no = row.bill_no or "COSU0001001"
        row.vessel_name = row.vessel_name or "YM WISH"
        row.voyage_no = row.voyage_no or "V03"
        row.gross_weight = row.gross_weight or Decimal("4200")
        row.net_weight = row.net_weight or Decimal("4000")
        row.length = row.length or Decimal("600")
        row.width = row.width or Decimal("200")
        row.height = row.height or Decimal("10")
        row.volume = row.volume or Decimal("1.2")
        row.box_no = row.box_no or "BOX-WMS-01"
        row.po_no = row.po_no or "PO-WMS-001"
        row.material_name_en = row.material_name_en or "Hot rolled plate"
        db.flush()
