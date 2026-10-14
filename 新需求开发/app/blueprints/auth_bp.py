import re

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from app.auth import current_user, login_required, new_csrf, verify_password
from app.db import begin_immediate, get_db, log_op
from app.utils import clean_text
from app import safe_next

bp = Blueprint("auth", __name__)
LOGIN_RE = re.compile(r"^[A-Za-z]+$")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("contracts.index"))
    error = ""
    login_name = ""
    nxt = safe_next(request.args.get("next") or request.form.get("next"))
    if request.method == "POST":
        login_name = (request.form.get("login_name") or "").strip()
        password = request.form.get("password") or ""
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE login_name=?",
            (login_name,),
        ).fetchone()
        if not user or not verify_password(user, password):
            begin_immediate(db)
            log_op(db, user, "login_fail", f"登录失败：{login_name or '空登录名'}")
            db.commit()
            error = "登录名或密码错误"
        elif user["status"] != "active":
            begin_immediate(db)
            log_op(db, user, "login_fail", f"禁用账号尝试登录：{login_name}")
            db.commit()
            error = "账号已禁用"
        else:
            begin_immediate(db)
            log_op(db, user, "login", f"{user['display_name']} 登录系统")
            db.commit()
            session.clear()
            session.permanent = True
            session["uid"] = user["id"]
            new_csrf()
            flash(f"欢迎，{user['display_name']}", "success")
            return redirect(safe_next(request.form.get("next")))
    return render_template("login.html", error=error, login_name=login_name, next_url=nxt)


@bp.route("/logout", methods=["POST"])
def logout():
    user = current_user()
    if user:
        db = get_db()
        begin_immediate(db)
        log_op(db, user, "logout", f"{user['display_name']} 退出系统")
        db.commit()
    session.clear()
    flash("已退出登录", "success")
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=["GET", "POST"])
@login_required
def password():
    user = current_user()
    errors = []
    if request.method == "POST":
        old = request.form.get("old_password") or ""
        new = request.form.get("new_password") or ""
        again = request.form.get("new_password2") or ""
        if not verify_password(user, old):
            errors.append("原密码不正确")
        if len(new) < 6 or len(new) > 64:
            errors.append("新密码长度需为 6 到 64 位")
        if new != again:
            errors.append("两次输入的新密码不一致")
        if not errors:
            db = get_db()
            begin_immediate(db)
            db.execute(
                "UPDATE users SET password_hash=?, updated_at=datetime('now','localtime') WHERE id=?",
                (generate_password_hash(new), user["id"]),
            )
            log_op(db, user, "password_change", f"{user['display_name']} 修改了本人密码")
            db.commit()
            flash("密码已修改", "success")
            return redirect(url_for("contracts.index"))
    return render_template("password.html", errors=errors)


def validate_login_name(value, required=True):
    text = clean_text(value, 32, "登录名", required=required)
    if text and not LOGIN_RE.match(text):
        raise ValueError("登录名必须为字母")
    return text
