from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .config import JWT_HOURS, JWT_SECRET

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        ok = _ph.verify(password_hash, password)
        return bool(ok)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def make_token(user, company_id: int) -> str:
    payload = {
        "employee_id": user.employee_id,
        "is_super_admin": bool(user.is_super_admin),
        "company_id": int(company_id),
        "auth_version": int(user.auth_version),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
