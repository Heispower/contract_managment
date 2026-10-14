import secrets
from functools import wraps

from flask import abort, redirect, request, session, url_for
from werkzeug.security import check_password_hash

from app.db import get_db, get_setting


def current_user():
    from flask import g

    if getattr(g, "user_loaded", False):
        return g.user
    g.user_loaded = True
    g.user = None
    uid = session.get("uid")
    if not uid:
        return None
    row = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row or row["status"] != "active":
        session.clear()
        return None
    g.user = row
    return row


def can_write(user):
    return bool(user) and user["role"] in ("admin", "user")


def can_mutate(user, record):
    if not can_write(user) or record is None:
        return False
    if user["role"] == "admin":
        return True
    return record["created_by"] == user["id"]


def can_manual(user):
    if not user or user["role"] == "viewer":
        return False
    if user["role"] == "admin":
        return True
    return get_setting("allow_user_manual_edit", "0") == "1"


def can_rate(user):
    if not user or user["role"] == "viewer":
        return False
    if user["role"] == "admin":
        return True
    return int(user["allow_rate"] or 0) == 1


def verify_password(user, password):
    return check_password_hash(user["password_hash"], password or "")


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            nxt = request.path if request.path.startswith("/") else "/"
            return redirect(url_for("auth.login", next=nxt))
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("auth.login", next=request.path))
        if user["role"] != "admin":
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


def new_csrf():
    session["csrf"] = secrets.token_hex(16)
    return session["csrf"]
