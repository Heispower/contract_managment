"""查询、乐观锁、删除、编号与操作日志。"""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import object_session

from ..errors import BizError
from ..models import (
    Contract,
    ContractOrder,
    OpLog,
    SysConfig,
    SysUser,
    SysUserCompany,
    now,
)
from ..money import D

MSG_LOCK = "数据已被他人修改，请刷新"
MSG_PERM = "无权修改，仅创建者可修改"
MSG_REF = "后续已生成单据，无法删除。"
MSG_CLOSE = "订单尚未完成，无法关闭"
MSG_LOCKED_ACCOUNT = "账号已锁定"
MSG_DISABLED = "账号已停用"
MSG_CODE = "编号已存在"
MSG_DIRECTION = "方向不一致"
MSG_NOT_SIGNED = "未签订与已终止的合同不能新建后续单据"
MSG_ADJUST = "请先调整订单、发票或出入库"


def alive(model):
    return model.deleted_at.is_(None)


def q(db, model, company_id):
    return db.query(model).filter(model.company_id == company_id, alive(model))


def get_row(db, model, row_id, company_id, *, include_deleted=False):
    try:
        key = int(row_id)
    except (TypeError, ValueError):
        raise BizError("数据不存在")
    row = db.get(model, key)
    if row is None or row.company_id != company_id:
        raise BizError("数据不存在")
    if row.deleted_at and not include_deleted:
        raise BizError("数据不存在")
    return row


def ensure_version(row, version):
    if version is None or int(version) != int(row.version):
        raise BizError(MSG_LOCK, 409)


def bump(row, employee_id: str):
    row.version = int(row.version or 1) + 1
    row.updated_by = employee_id
    row.updated_at = now()


def stamp_new(row, user, company_id: int):
    row.company_id = company_id
    row.created_by = user.employee_id
    row.updated_by = user.employee_id
    row.created_at = now()
    row.updated_at = now()
    row.version = 1


def soft_delete(row, employee_id: str):
    """表单删除即物理删除。记录不再留在库里，编号和主键可以重新使用。"""
    session = object_session(row)
    if session is None:
        raise BizError("数据不存在")
    if isinstance(row, SysUser):
        session.query(SysUserCompany).filter(SysUserCompany.employee_id == row.employee_id).delete(synchronize_session=False)
    session.delete(row)
    _ = employee_id


def purge_deleted_rows(db):
    """清掉历史上软删除、仍占用唯一编号的行。"""
    from ..database import Base

    for table in Base.metadata.sorted_tables:
        if "deleted_at" not in table.c:
            continue
        db.execute(text(f"DELETE FROM {table.name} WHERE deleted_at IS NOT NULL"))
    db.execute(text("DELETE FROM sys_user_company WHERE employee_id NOT IN (SELECT employee_id FROM sys_user)"))


def ensure_creator(row, user, *, supplement: bool = False):
    if supplement:
        return
    if row.created_by != user.employee_id:
        raise BizError(MSG_PERM, 403)


def can_overwrite(user, created_by: str) -> bool:
    if user.is_super_admin or user.can_import_overwrite:
        return True
    return created_by == user.employee_id


def op_log(db, user, company_id, action, biz_type, biz_id, detail):
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False, default=str)
    db.add(
        OpLog(
            operator=user.employee_id,
            company_id=company_id,
            action=action,
            biz_type=biz_type,
            biz_id=str(biz_id or ""),
            detail=detail,
            ip="127.0.0.1",
            created_at=now(),
        )
    )


def parse_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise BizError(f"日期格式不正确：{text}")


def page_args(page, page_size):
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 50), 1), 500)
    return page, page_size


def config_int(db, name: str, default: int) -> int:
    row = db.query(SysConfig).filter(SysConfig.config_name == name, SysConfig.deleted_at.is_(None)).first()
    if not row:
        return default
    try:
        return int(Decimal(str(row.config_value)))
    except Exception:
        return default


def user_names(db, employee_ids) -> dict:
    ids = [i for i in set(employee_ids) if i]
    if not ids:
        return {}
    rows = db.query(SysUser).filter(SysUser.employee_id.in_(ids)).all()
    return {r.employee_id: r.name for r in rows}


def name_of(names: dict, employee_id: str | None) -> str:
    if not employee_id:
        return ""
    return names.get(employee_id) or employee_id


def find_by_code(db, model, company_id, column, code):
    return (
        db.query(model)
        .filter(model.company_id == company_id, column == code)
        .first()
    )


def ensure_code_free(db, model, company_id, column, code, self_id=None):
    row = find_by_code(db, model, company_id, column, code)
    if row and row.id != self_id:
        raise BizError(MSG_CODE)


def next_daily_code(db, model, company_id, column, prefix: str) -> str:
    day = datetime.now().strftime("%Y%m%d")
    base = f"{prefix}-{day}-"
    rows = db.query(column).filter(model.company_id == company_id, column.like(base + "%")).all()
    n = 0
    for (code,) in rows:
        tail = str(code)[len(base) :]
        if tail.isdigit():
            n = max(n, int(tail))
    return f"{base}{n + 1:03d}"


def next_contract_code(db, company_id, direction: str) -> str:
    prefix = "XS" if direction == "sale" else "CG"
    year = datetime.now().year
    base = f"{prefix}-{year}-"
    rows = (
        db.query(Contract.contract_code)
        .filter(Contract.company_id == company_id, Contract.contract_code.like(base + "%"))
        .all()
    )
    n = 0
    for (code,) in rows:
        tail = str(code)[len(base) :]
        if tail.isdigit():
            n = max(n, int(tail))
    return f"{base}{n + 1:03d}"


def next_supplement_code(db, company_id, parent_code: str) -> str:
    prefix = f"{parent_code}-补"
    rows = (
        db.query(Contract.contract_code)
        .filter(Contract.company_id == company_id, Contract.contract_code.like(prefix + "%"))
        .all()
    )
    n = 0
    for (code,) in rows:
        tail = str(code)[len(prefix) :]
        if tail.isdigit():
            n = max(n, int(tail))
    return f"{prefix}{n + 1}"


def next_order_code(db, company_id, contract_code: str) -> str:
    base = "order" + contract_code
    exact = (
        db.query(ContractOrder)
        .filter(ContractOrder.company_id == company_id, ContractOrder.order_code == base)
        .first()
    )
    if exact is None:
        return base
    n = 1
    while True:
        code = f"{base}-R{n:02d}"
        taken = (
            db.query(ContractOrder.id)
            .filter(ContractOrder.company_id == company_id, ContractOrder.order_code == code)
            .first()
        )
        if taken is None:
            return code
        n += 1


def accessible_company_ids(db, user) -> list[int]:
    if user.is_super_admin:
        from ..models import Company

        return [r.id for r in db.query(Company).filter(Company.deleted_at.is_(None)).order_by(Company.id).all()]
    rows = db.query(SysUserCompany).filter(SysUserCompany.employee_id == user.employee_id).all()
    return [r.company_id for r in rows]


def default_company_id(db, user):
    if user.is_super_admin:
        rel = (
            db.query(SysUserCompany)
            .filter(SysUserCompany.employee_id == user.employee_id, SysUserCompany.is_default.is_(True))
            .first()
        )
        if rel:
            return rel.company_id
        ids = accessible_company_ids(db, user)
        return ids[0] if ids else None
    rel = (
        db.query(SysUserCompany)
        .filter(SysUserCompany.employee_id == user.employee_id, SysUserCompany.is_default.is_(True))
        .first()
    )
    if rel:
        return rel.company_id
    ids = accessible_company_ids(db, user)
    return ids[0] if ids else None


def lock_until(db):
    minutes = config_int(db, "登录锁定时长（分钟）", 30)
    return now() + timedelta(minutes=minutes)


def fail_limit(db) -> int:
    return config_int(db, "登录失败锁定次数", 5)


def min_password(db) -> int:
    return config_int(db, "密码最小长度", 6)


def as_decimal(value, label="金额"):
    try:
        return D(value)
    except Exception as exc:
        raise BizError(f"{label}格式不正确") from exc
