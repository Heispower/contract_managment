import jwt
from fastapi import Depends, Request

from .database import get_db
from .errors import BizError
from .models import SysUser, SysUserCompany
from .security import decode_token


def current_user(request: Request, db=Depends(get_db)):
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise BizError("未登录", 401)
    token = header.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise BizError("未登录", 401) from exc
    user = db.query(SysUser).filter(SysUser.employee_id == payload.get("employee_id")).first()
    if user is None or user.deleted_at or int(user.auth_version) != int(payload.get("auth_version")):
        raise BizError("未登录", 401)
    if user.status != "启用":
        raise BizError("账号已停用", 401)
    company_id = int(payload.get("company_id"))
    for raw in (request.headers.get("x-company-id"), request.query_params.get("company_id")):
        if raw not in (None, "") and int(raw) != company_id:
            raise BizError("跨公司越权", 403)
    if not user.is_super_admin:
        rel = (
            db.query(SysUserCompany)
            .filter(SysUserCompany.employee_id == user.employee_id, SysUserCompany.company_id == company_id)
            .first()
        )
        if rel is None:
            raise BizError("跨公司越权", 403)
    user.session_company_id = company_id
    return user
