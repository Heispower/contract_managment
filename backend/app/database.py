"""SQLite。写事务使用 BEGIN IMMEDIATE，把额度争用串行化。

SQLite 没有 SELECT ... FOR UPDATE。本系统把数据库放在本机单文件里，
BEGIN IMMEDIATE 会占住写锁，后到的事务等到提交后再读最新值，效果与 3.7 的行锁一致。
"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DB_PATH

_engine = None
SessionLocal = None


class Base(DeclarativeBase):
    pass


def _build(path: str):
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def on_connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    @event.listens_for(engine, "begin")
    def on_begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def init_engine(path: str | None = None):
    global _engine, SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = _build(path or DB_PATH)
    SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_engine():
    if _engine is None:
        init_engine()
    return _engine


def get_session():
    if SessionLocal is None:
        init_engine()
    return SessionLocal()


def get_db():
    db = get_session()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def ensure_columns(table: str, columns: dict[str, str]):
    engine = get_engine()
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
        if not existing:
            return
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def ensure_company_columns():
    """公司资料与客商使用同一套开票、银行和联系人字段。"""
    ensure_columns("company", {
        "code": "VARCHAR(64)",
        "status": "VARCHAR(20) DEFAULT '启用'",
        "default_tax_rate": "VARCHAR(40)",
        "salesman_id": "VARCHAR(64)",
        "invoice_title": "VARCHAR(200)",
        "email": "VARCHAR(100)",
        "mobile": "VARCHAR(50)",
        "bank_name": "VARCHAR(200)",
        "account_name": "VARCHAR(200)",
        "bank_account": "VARCHAR(64)",
        "bank_branch": "VARCHAR(200)",
        "invoice_phone": "VARCHAR(50)",
        "invoice_address": "VARCHAR(255)",
        "legal_name": "VARCHAR(100)",
        "agent_name": "VARCHAR(100)",
        "remark": "TEXT",
    })


def ensure_project_columns():
    """项目筛选需要类型、来源和起止日期。已有库补列，不改已填内容。"""
    ensure_columns("project", {
        "project_type": "VARCHAR(100)",
        "source": "VARCHAR(100)",
        "start_date": "DATE",
        "end_date": "DATE",
    })


def ensure_party_columns():
    """已有库补齐客商模板里的开票、银行和联系方式，以及合同上的对方快照。"""
    ensure_columns("party", {
        "email": "VARCHAR(100)",
        "mobile": "VARCHAR(50)",
        "bank_name": "VARCHAR(200)",
        "account_name": "VARCHAR(200)",
        "bank_branch": "VARCHAR(200)",
        "invoice_phone": "VARCHAR(50)",
        "invoice_address": "VARCHAR(255)",
        "legal_name": "VARCHAR(100)",
        "agent_name": "VARCHAR(100)",
        "remark": "TEXT",
    })
    ensure_columns("contract", {
        "party_bank_name": "VARCHAR(200)",
        "party_account_name": "VARCHAR(200)",
        "party_bank_account": "VARCHAR(64)",
        "party_bank_branch": "VARCHAR(200)",
        "party_invoice_title": "VARCHAR(200)",
        "party_invoice_phone": "VARCHAR(50)",
        "party_invoice_address": "VARCHAR(255)",
        "party_address": "VARCHAR(255)",
        "party_legal_name": "VARCHAR(100)",
        "party_agent": "VARCHAR(100)",
        "subject_name": "VARCHAR(200)",
        "transport_mode": "VARCHAR(100)",
        "delivery_term": "VARCHAR(200)",
        "freight_bearer": "VARCHAR(100)",
        "receiver_name": "VARCHAR(100)",
        "acceptance_text": "TEXT",
        "annex_note": "VARCHAR(255)",
    })


def ensure_customs_form_columns():
    """报关发票三页和 Excel 模板要用的物料、发票字段。已有库补列。"""
    shared = {
        "package_count": "INTEGER",
        "inquiry_name": "VARCHAR(200)",
        "inquiry_model": "VARCHAR(200)",
        "inquiry_qty": "VARCHAR(40)",
        "port_of_shipment": "VARCHAR(100)",
        "port_of_destination": "VARCHAR(100)",
        "consignee": "VARCHAR(200)",
        "payment_terms": "VARCHAR(255)",
        "hs_code": "VARCHAR(32)",
        "declaration_elements": "TEXT",
        "remark": "VARCHAR(255)",
    }
    for table in ("warehouse_receipt_item", "customs_stock", "customs_material"):
        ensure_columns(table, shared)
    ensure_columns("customs_invoice", {
        "invoice_date_2": "DATE",
        "packing_list_no": "VARCHAR(64)",
        "vessel_voyage": "VARCHAR(200)",
        "container_no": "VARCHAR(500)",
        "bl_no": "VARCHAR(200)",
        "port_of_shipment": "VARCHAR(100)",
        "port_of_destination": "VARCHAR(100)",
        "customs_elements": "TEXT",
        "exchange_rate": "VARCHAR(40)",
        "total_usd": "VARCHAR(32)",
        "po_no": "VARCHAR(200)",
        "payment_terms": "VARCHAR(255)",
        "consignee": "VARCHAR(200)",
    })
    ensure_columns("customs_clearance", {
        "port_of_shipment": "VARCHAR(100)",
        "packing_list_no": "VARCHAR(64)",
    })
    ensure_columns("customs_clearance_pl", {
        "receipt_no": "VARCHAR(200)",
    })


def ensure_hs_columns():
    """HS Code 库的产品名称可空，已有库补列。"""
    ensure_columns("hs_code_library", {"product_name": "VARCHAR(200)"})


def ensure_item_category_columns():
    """采购计划的使用设备要落到合同明细和入库明细。"""
    ensure_columns("contract_item", {"category": "VARCHAR(100)"})
    ensure_columns("wms_item", {"category": "VARCHAR(100)"})
    ensure_columns("customs_material", {
        "wms_bill_id": "INTEGER",
        "wms_item_id": "INTEGER",
    })


def ping():
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
