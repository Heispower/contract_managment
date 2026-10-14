"""数据模型。业务表统一 company_id、审计字段、乐观锁 version、软删除与三个保留字段。"""
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .money import D, round2


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


class Money(TypeDecorator):
    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return format(round2(value), "f")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value)


class Qty(TypeDecorator):
    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return format(D(value), "f")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value)


class Audit:
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_by: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reserve1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reserve2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reserve3: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CompanyScoped(Audit):
    company_id: Mapped[int] = mapped_column(Integer, index=True)


class Company(Base, Audit):
    __tablename__ = "company"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="启用")
    default_tax_rate: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    salesman_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tax_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invoice_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bank_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    invoice_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    invoice_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legal_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class CompanyContact(Base, Audit):
    __tablename__ = "company_contact"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class SysUser(Base, Audit):
    __tablename__ = "sys_user"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(64), unique=True)
    login_name: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    role_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dept_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="启用")
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    can_import_overwrite: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    auth_version: Mapped[int] = mapped_column(Integer, default=1)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)


class SysUserCompany(Base):
    __tablename__ = "sys_user_company"
    __table_args__ = (
        UniqueConstraint("employee_id", "company_id", name="uq_user_company"),
        Index("uq_user_default_company", "employee_id", unique=True, sqlite_where=text("is_default = 1")),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(64), index=True)
    company_id: Mapped[int] = mapped_column(Integer, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class SysRole(Base, CompanyScoped):
    __tablename__ = "sys_role"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_role_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SysDept(Base, CompanyScoped):
    __tablename__ = "sys_dept"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_dept_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SysPost(Base, CompanyScoped):
    __tablename__ = "sys_post"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_post_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SysConfig(Base, Audit):
    __tablename__ = "sys_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_name: Mapped[str] = mapped_column(String(100), unique=True)
    config_value: Mapped[str] = mapped_column(String(255))


class LoginLog(Base):
    __tablename__ = "login_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user: Mapped[str] = mapped_column(String(64))
    login_time: Mapped[datetime] = mapped_column(DateTime, default=now)
    ip: Mapped[str] = mapped_column(String(64), default="127.0.0.1")
    result: Mapped[str] = mapped_column(String(20), default="成功")


class OpLog(Base):
    __tablename__ = "op_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operator: Mapped[str] = mapped_column(String(64))
    company_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    biz_type: Mapped[str] = mapped_column(String(50))
    biz_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="127.0.0.1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Party(Base, CompanyScoped):
    __tablename__ = "party"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_party_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    type: Mapped[str] = mapped_column(String(20))
    tax_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_tax_rate: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="启用")
    supplier_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    salesman_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invoice_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bank_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    invoice_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    invoice_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legal_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class PartyContact(Base, CompanyScoped):
    __tablename__ = "party_contact"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    party_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Project(Base, CompanyScoped):
    __tablename__ = "project"
    __table_args__ = (UniqueConstraint("company_id", "project_code", name="uq_project_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    year: Mapped[str | None] = mapped_column(String(20), nullable=True)
    project_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="进行中")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class FundAccount(Base, CompanyScoped):
    __tablename__ = "fund_account"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_fund_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    account_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="启用")


class ContractType(Base, CompanyScoped):
    __tablename__ = "contract_type"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_ctype_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="启用")


class ExportProfile(Base, CompanyScoped):
    """一张单据可以维护多份导出模板。模板用绝对地址，下载名按占位符拼。"""
    __tablename__ = "export_profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_code: Mapped[str] = mapped_column(String(40))
    doc_name: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(100), default="")
    template_file: Mapped[str] = mapped_column(String(255), default="")
    template_path: Mapped[str] = mapped_column(Text, default="")
    party_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name_rule: Mapped[str] = mapped_column(String(255), default="")
    sort_no: Mapped[int] = mapped_column(Integer, default=0)


class Warehouse(Base, CompanyScoped):
    __tablename__ = "warehouse"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_wh_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="启用")


class GoodsCategory(Base, CompanyScoped):
    __tablename__ = "goods_category"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_gcat_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Goods(Base, CompanyScoped):
    __tablename__ = "goods"
    __table_args__ = (UniqueConstraint("company_id", "material_code", name="uq_goods_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    spec: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit: Mapped[str] = mapped_column(String(20))
    category_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)


class PurchasePlan(Base, CompanyScoped):
    __tablename__ = "purchase_plan"
    __table_args__ = (UniqueConstraint("company_id", "material_code", name="uq_plan_material"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_month: Mapped[str | None] = mapped_column(String(20), nullable=True)
    purchase_seq: Mapped[str | None] = mapped_column(String(64), nullable=True)
    material_code: Mapped[str] = mapped_column(String(64))
    plan_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name_cn: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spec: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    purpose: Mapped[str | None] = mapped_column(String(200), nullable=True)
    use_dept: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stock_qty: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    transit_qty: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    consume_4m: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class Contract(Base, CompanyScoped):
    __tablename__ = "contract"
    __table_args__ = (UniqueConstraint("company_id", "contract_code", name="uq_contract_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    nature: Mapped[str] = mapped_column(String(20), default="main")
    parent_contract_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    direction: Mapped[str] = mapped_column(String(20))
    type_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    party_id: Mapped[int] = mapped_column(Integer, index=True)
    party_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    party_tax_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="已签订")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sign_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    pricing: Mapped[str] = mapped_column(String(20), default="fixed")
    tax_rate: Mapped[Decimal] = mapped_column(Qty, default=Decimal("13"))
    amount_manual: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    amount_ex_tax: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    settled_sum: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    arrival_stage_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ship_stage_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ship_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    party_bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    party_account_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    party_bank_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    party_bank_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    party_invoice_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    party_invoice_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    party_invoice_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    party_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    party_legal_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    party_agent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    subject_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    transport_mode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_term: Mapped[str | None] = mapped_column(String(200), nullable=True)
    freight_bearer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    receiver_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acceptance_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    annex_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invoice_locked: Mapped[bool] = mapped_column(Boolean, default=False)


class ContractItem(Base, CompanyScoped):
    __tablename__ = "contract_item"
    __table_args__ = (
        Index(
            "uq_contract_item_mat",
            "contract_id",
            "material_code",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(Integer, index=True)
    material_code: Mapped[str] = mapped_column(String(64))
    name_cn: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spec: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    plan_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ContractStage(Base, CompanyScoped):
    __tablename__ = "contract_stage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(50))
    ratio: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    plan_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    plan_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    settled_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    arrival_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    ship_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ContractOrder(Base, CompanyScoped):
    __tablename__ = "contract_order"
    __table_args__ = (
        UniqueConstraint("company_id", "order_code", name="uq_order_code"),
        Index(
            "uq_order_active_contract",
            "company_id",
            "contract_id",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_code: Mapped[str] = mapped_column(String(80))
    contract_id: Mapped[int] = mapped_column(Integer, index=True)
    direction: Mapped[str] = mapped_column(String(20))
    party_id: Mapped[int] = mapped_column(Integer)
    tax_rate: Mapped[Decimal] = mapped_column(Qty, default=Decimal("13"))
    owner_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="open")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))


class OrderItem(Base, CompanyScoped):
    __tablename__ = "order_item"
    __table_args__ = (
        Index(
            "uq_order_item_mat",
            "order_id",
            "material_code",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    material_code: Mapped[str] = mapped_column(String(64))
    name_cn: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spec: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SettleBill(Base, CompanyScoped):
    __tablename__ = "settle_bill"
    __table_args__ = (UniqueConstraint("company_id", "bill_code", name="uq_settle_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_code: Mapped[str] = mapped_column(String(64))
    bill_date: Mapped[date] = mapped_column(Date)
    direction: Mapped[str] = mapped_column(String(20))
    party_id: Mapped[int] = mapped_column(Integer, index=True)
    party_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contract_id: Mapped[int] = mapped_column(Integer, index=True)
    stage_id: Mapped[int] = mapped_column(Integer, index=True)
    amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    account_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class OtherBill(Base, CompanyScoped):
    __tablename__ = "other_bill"
    __table_args__ = (UniqueConstraint("company_id", "bill_code", name="uq_other_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_code: Mapped[str] = mapped_column(String(64))
    bill_date: Mapped[date] = mapped_column(Date)
    direction: Mapped[str] = mapped_column(String(20))
    party_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contract_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    account_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class Invoice(Base, CompanyScoped):
    __tablename__ = "invoice"
    __table_args__ = (
        UniqueConstraint("company_id", "bill_code", name="uq_invoice_bill"),
        UniqueConstraint("company_id", "invoice_no", name="uq_invoice_no"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_code: Mapped[str] = mapped_column(String(64))
    invoice_no: Mapped[str] = mapped_column(String(64))
    invoice_date: Mapped[date] = mapped_column(Date)
    invoice_type: Mapped[str] = mapped_column(String(40), default="增值税专用发票")
    direction: Mapped[str] = mapped_column(String(20))
    party_id: Mapped[int] = mapped_column(Integer, index=True)
    party_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    party_tax_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contract_id: Mapped[int] = mapped_column(Integer, index=True)
    attachments: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_ex_tax: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    tax: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))


class InvoiceItem(Base, CompanyScoped):
    __tablename__ = "invoice_item"
    __table_args__ = (
        Index(
            "uq_invoice_item_mat",
            "invoice_id",
            "material_code",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(Integer, index=True)
    material_code: Mapped[str] = mapped_column(String(64))
    name_cn: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spec: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    price_ex_tax: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    price: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    amount_ex_tax: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    tax_rate: Mapped[Decimal] = mapped_column(Qty, default=Decimal("13"))
    tax: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manual_tax: Mapped[bool] = mapped_column(Boolean, default=False)


class WmsBill(Base, CompanyScoped):
    __tablename__ = "wms_bill"
    __table_args__ = (UniqueConstraint("company_id", "bill_code", name="uq_wms_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_code: Mapped[str] = mapped_column(String(64))
    bill_date: Mapped[date] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(20))
    contract_id: Mapped[int] = mapped_column(Integer, index=True)
    party_id: Mapped[int] = mapped_column(Integer)
    party_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    warehouse_id: Mapped[int] = mapped_column(Integer)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class WmsItem(Base, CompanyScoped):
    __tablename__ = "wms_item"
    __table_args__ = (
        Index(
            "uq_wms_item_mat",
            "bill_id",
            "material_code",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_id: Mapped[int] = mapped_column(Integer, index=True)
    material_code: Mapped[str] = mapped_column(String(64))
    name_cn: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spec: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Stock(Base, CompanyScoped):
    __tablename__ = "stock"
    __table_args__ = (
        UniqueConstraint("company_id", "warehouse_id", "material_code", name="uq_stock"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(Integer)
    material_code: Mapped[str] = mapped_column(String(64))
    goods_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    goods_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    cost: Mapped[Decimal | None] = mapped_column(Money, nullable=True)


class TransferBill(Base, CompanyScoped):
    __tablename__ = "transfer_bill"
    __table_args__ = (UniqueConstraint("company_id", "bill_code", name="uq_transfer_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_code: Mapped[str] = mapped_column(String(64))
    bill_date: Mapped[date] = mapped_column(Date)
    warehouse_out: Mapped[int] = mapped_column(Integer)
    warehouse_in: Mapped[int] = mapped_column(Integer)
    material_code: Mapped[str] = mapped_column(String(64))
    qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class CheckBill(Base, CompanyScoped):
    __tablename__ = "check_bill"
    __table_args__ = (UniqueConstraint("company_id", "bill_code", name="uq_check_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_code: Mapped[str] = mapped_column(String(64))
    bill_date: Mapped[date] = mapped_column(Date)
    warehouse_id: Mapped[int] = mapped_column(Integer)
    material_code: Mapped[str] = mapped_column(String(64))
    book_qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    actual_qty: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReminderRecord(Base, CompanyScoped):
    __tablename__ = "reminder_record"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    biz_type: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(20))
    biz_code: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="unhandled")
    handled_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ImportIdem(Base):
    __tablename__ = "import_idem"
    __table_args__ = (
        UniqueConstraint("company_id", "module", "mode", "file_hash", name="uq_import_idem"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(Integer)
    module: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(40))
    file_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class WarehouseReceipt(Base, CompanyScoped):
    """报关入仓单。与合同仓储入库分开，原始物料只在这里录一次。"""
    __tablename__ = "warehouse_receipt"
    __table_args__ = (UniqueConstraint("company_id", "receipt_no", name="uq_wh_receipt_no"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_no: Mapped[str] = mapped_column(String(64))
    receipt_date: Mapped[date] = mapped_column(Date)
    supplier_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contract_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    packing_list_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="草稿")


class WarehouseReceiptItem(Base, CompanyScoped):
    __tablename__ = "warehouse_receipt_item"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(Integer, index=True)
    material_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    material_code: Mapped[str] = mapped_column(String(64))
    material_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    material_name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    specification: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    origin_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    equipment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    box_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    container_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bill_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vessel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    voyage_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gross_weight: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    net_weight: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    length: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    width: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    height: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    po_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    package_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inquiry_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    inquiry_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    inquiry_qty: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    port_of_shipment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    port_of_destination: Mapped[str | None] = mapped_column(String(100), nullable=True)
    consignee: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hs_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    declaration_elements: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    special_declare: Mapped[bool] = mapped_column(Boolean, default=False)


class CustomsStock(Base, CompanyScoped):
    """入仓明细进入库存时保留 receipt_item_id，原始字段不丢。"""
    __tablename__ = "customs_stock"
    __table_args__ = (UniqueConstraint("company_id", "receipt_item_id", name="uq_customs_stock_item"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(Integer, index=True)
    receipt_item_id: Mapped[int] = mapped_column(Integer, index=True)
    receipt_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contract_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    packing_list_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    material_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    material_code: Mapped[str] = mapped_column(String(64))
    material_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    material_name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    specification: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    origin_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    equipment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    box_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    container_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bill_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vessel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    voyage_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gross_weight: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    net_weight: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    length: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    width: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    height: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    po_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    package_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inquiry_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    inquiry_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    inquiry_qty: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    port_of_shipment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    port_of_destination: Mapped[str | None] = mapped_column(String(100), nullable=True)
    consignee: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hs_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    declaration_elements: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    special_declare: Mapped[bool] = mapped_column(Boolean, default=False)


class CustomsMaterial(Base, CompanyScoped):
    __tablename__ = "customs_material"
    __table_args__ = (UniqueConstraint("company_id", "receipt_item_id", name="uq_customs_mat_item"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(Integer, index=True)
    receipt_item_id: Mapped[int] = mapped_column(Integer, index=True)
    wms_bill_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    wms_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    receipt_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contract_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    packing_list_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    material_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    material_code: Mapped[str] = mapped_column(String(64))
    material_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    material_name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    specification: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    origin_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    equipment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    box_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    container_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bill_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vessel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    voyage_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gross_weight: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    net_weight: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    length: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    width: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    height: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    po_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    package_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inquiry_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    inquiry_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    inquiry_qty: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    port_of_shipment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    port_of_destination: Mapped[str | None] = mapped_column(String(100), nullable=True)
    consignee: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hs_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    declaration_elements: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    special_declare: Mapped[bool] = mapped_column(Boolean, default=False)
    invoice_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clearance_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    element_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="正常")


class CustomsInvoice(Base, CompanyScoped):
    __tablename__ = "customs_invoice"
    __table_args__ = (
        UniqueConstraint("company_id", "invoice_no", name="uq_customs_inv_no"),
        UniqueConstraint("customs_element_id", name="uq_customs_inv_element"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(64))
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(10), default="CNY")
    invoice_date_2: Mapped[date | None] = mapped_column(Date, nullable=True)
    packing_list_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vessel_voyage: Mapped[str | None] = mapped_column(String(200), nullable=True)
    container_no: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bl_no: Mapped[str | None] = mapped_column(String(200), nullable=True)
    port_of_shipment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    port_of_destination: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customs_elements: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    total_usd: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    po_no: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    consignee: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customs_element_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    element_status: Mapped[str] = mapped_column(String(20), default="未关联")
    status: Mapped[str] = mapped_column(String(20), default="已生成")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class CustomsInvoiceItem(Base, CompanyScoped):
    __tablename__ = "customs_invoice_item"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    name_cn: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    specification: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    packages: Mapped[int] = mapped_column(Integer, default=0)
    special_declare: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    equipment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_no: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CustomsInvoiceLink(Base, CompanyScoped):
    __tablename__ = "customs_invoice_link"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(Integer, index=True)
    material_id: Mapped[int] = mapped_column(Integer, index=True)


class CustomsClearance(Base, CompanyScoped):
    __tablename__ = "customs_clearance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    vessel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    voyage_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    container_no: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bill_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    port_of_shipment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    packing_list_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total_usd: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(20), default="已生成")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class CustomsClearanceItem(Base, CompanyScoped):
    __tablename__ = "customs_clearance_item"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clearance_id: Mapped[int] = mapped_column(Integer, index=True)
    material_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    name_cn: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    specification: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    amount_usd: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    po_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CustomsClearancePl(Base, CompanyScoped):
    __tablename__ = "customs_clearance_pl"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clearance_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    specification: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    packages: Mapped[int] = mapped_column(Integer, default=0)
    gross_weight: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    net_weight: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    size_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    receipt_no: Mapped[str | None] = mapped_column(String(200), nullable=True)


class CustomsElement(Base, CompanyScoped):
    __tablename__ = "customs_element"
    __table_args__ = (UniqueConstraint("invoice_id", name="uq_customs_el_invoice"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="已生成")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class CustomsElementItem(Base, CompanyScoped):
    __tablename__ = "customs_element_item"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    element_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    hs_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    declaration_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    specification: Mapped[str | None] = mapped_column(String(200), nullable=True)
    declaration_elements: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    special_declare: Mapped[bool] = mapped_column(Boolean, default=False)
    match_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    match_score: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)


class CustomsElementLine(Base, CompanyScoped):
    """同一 HS、申报名称下的产品行。对应模板里的产品名称、型号、申报要素、货源地。"""
    __tablename__ = "customs_element_line"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    element_item_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    product_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    declaration_elements: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_place: Mapped[str | None] = mapped_column(String(100), nullable=True)


class HsCodeLibrary(Base, CompanyScoped):
    __tablename__ = "hs_code_library"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hs_code: Mapped[str] = mapped_column(String(32))
    declaration_name: Mapped[str] = mapped_column(String(200))
    product_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    specification: Mapped[str | None] = mapped_column(String(200), nullable=True)
    declaration_elements: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="启用")


class ExchangeRate(Base, CompanyScoped):
    __tablename__ = "exchange_rate"
    __table_args__ = (UniqueConstraint("company_id", "year", "month", "currency", name="uq_fx_month"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    rate: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class DeepseekSetting(Base, CompanyScoped):
    """每个公司一份 Deepseek 配置，报关要素检查直接读取。"""
    __tablename__ = "deepseek_setting"
    __table_args__ = (UniqueConstraint("company_id", name="uq_deepseek_company"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    api_base: Mapped[str] = mapped_column(String(255), default="https://api.deepseek.com")
    api_key: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str] = mapped_column(String(64), default="deepseek-v4-flash")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    temperature: Mapped[str] = mapped_column(String(16), default="0.2")
    thinking: Mapped[bool] = mapped_column(Boolean, default=False)


class BizFile(Base, CompanyScoped):
    __tablename__ = "biz_file"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(Text)
    file_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    business_type: Mapped[str] = mapped_column(String(40))
    business_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(20), default="启用")
