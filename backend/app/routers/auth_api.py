from fastapi import APIRouter, Depends

from ..database import get_db
from ..deps import current_user
from ..errors import BizError
from ..models import Company, LoginLog, SysUser, now
from ..response import ok
from ..security import hash_password, make_token, verify_password
from ..services.seed import clear_business, seed_demo_business, wipe_all_data
from ..services.util import (
    MSG_DISABLED,
    MSG_LOCKED_ACCOUNT,
    accessible_company_ids,
    default_company_id,
    fail_limit,
    lock_until,
    min_password,
    op_log,
)

router = APIRouter(prefix="/api")


def _companies(db, user):
    ids = accessible_company_ids(db, user)
    if not ids:
        return []
    rows = db.query(Company).filter(Company.id.in_(ids), Company.deleted_at.is_(None)).order_by(Company.id).all()
    return [{"id": row.id, "name": row.name, "short_name": row.short_name, "tax_no": row.tax_no or "", "address": row.address or ""} for row in rows]


def _public_user(db, user):
    companies = _companies(db, user)
    return {
        "employee_id": user.employee_id,
        "login_name": user.login_name,
        "name": user.name,
        "is_super_admin": bool(user.is_super_admin),
        "can_import_overwrite": bool(user.is_super_admin or user.can_import_overwrite),
        "must_change_password": bool(user.must_change_password),
        "company_id": user.session_company_id,
        "companies": companies,
        "company_name": next((item["short_name"] for item in companies if item["id"] == user.session_company_id), ""),
    }


@router.post("/auth/login")
def login(payload: dict, db=Depends(get_db)):
    login_name = (payload.get("login_name") or payload.get("username") or "").strip()
    password = payload.get("password") or ""
    user = db.query(SysUser).filter(SysUser.login_name == login_name, SysUser.deleted_at.is_(None)).first()
    if user is None:
        raise BizError("用户名或密码错误")
    if user.status != "启用":
        raise BizError(MSG_DISABLED)
    if user.locked_until and user.locked_until > now():
        raise BizError(MSG_LOCKED_ACCOUNT)
    if not verify_password(password, user.password_hash):
        user.failed_login_count = int(user.failed_login_count or 0) + 1
        if user.failed_login_count >= fail_limit(db):
            user.locked_until = lock_until(db)
        db.commit()
        raise BizError("用户名或密码错误")
    user.failed_login_count = 0
    user.locked_until = None
    company_id = default_company_id(db, user)
    if not company_id:
        raise BizError("没有可访问的公司")
    user.session_company_id = company_id
    db.add(LoginLog(user=user.login_name, login_time=now(), ip="127.0.0.1", result="成功"))
    token = make_token(user, company_id)
    companies = _companies(db, user)
    return ok({
        "token": token,
        "need_choose_company": len(companies) > 1,
        "user": _public_user(db, user),
    })


@router.post("/auth/logout")
def logout(user=Depends(current_user)):
    return ok({"ok": True})


@router.get("/auth/me")
def me(user=Depends(current_user), db=Depends(get_db)):
    return ok(_public_user(db, user))


@router.post("/auth/change-password")
def change_password(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    old = payload.get("old_password") or ""
    new = payload.get("new_password") or ""
    if not verify_password(old, user.password_hash):
        raise BizError("用户名或密码错误")
    if len(new) < min_password(db):
        raise BizError(f"密码至少 {min_password(db)} 位")
    user.password_hash = hash_password(new)
    user.auth_version = int(user.auth_version) + 1
    user.must_change_password = False
    user.updated_at = now()
    token = make_token(user, user.session_company_id)
    op_log(db, user, user.session_company_id, "修改密码", "user", user.employee_id, "本人改密")
    return ok({"token": token})


@router.post("/auth/forgot-password")
def forgot(_payload: dict):
    return ok({"message": "邮件已发送"}, message="邮件已发送")


@router.post("/companies/switch")
def switch_company(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    company_id = int(payload.get("company_id"))
    if company_id not in accessible_company_ids(db, user):
        raise BizError("跨公司越权", 403)
    company = db.get(Company, company_id)
    token = make_token(user, company_id)
    op_log(db, user, company_id, "切换公司", "company", company_id, {"name": company.short_name if company else ""})
    user.session_company_id = company_id
    return ok({"token": token, "user": _public_user(db, user)})


@router.post("/settings/init-demo")
def init_demo(user=Depends(current_user), db=Depends(get_db)):
    if not user.is_super_admin:
        raise BizError("无权修改，仅创建者可修改", 403)
    clear_business(db)
    seed_demo_business(db)
    return ok({"ok": True})


@router.post("/settings/wipe")
def wipe_system(payload: dict, user=Depends(current_user), db=Depends(get_db)):
    if not user.is_super_admin:
        raise BizError("只有管理员可以清空数据", 403)
    if (payload.get("confirm") or "").strip() != "清空全部数据":
        raise BizError("请输入确认文字：清空全部数据")
    removed = wipe_all_data(db, user.employee_id, user.session_company_id)
    return ok({"removed": removed})
