from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from app.auth import admin_required, current_user
from app.blueprints.auth_bp import validate_login_name
from app.db import begin_immediate, get_db, get_setting, log_op, safe_rollback
from app.utils import build_pager, clean_text, form_dict, now_str, page_args, sort_sql

bp = Blueprint("users", __name__, url_prefix="/users")


def _admin_count(db, except_id=None):
    if except_id:
        row = db.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role='admin' AND status='active' AND id!=?",
            (except_id,),
        ).fetchone()
    else:
        row = db.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role='admin' AND status='active'"
        ).fetchone()
    return row["n"]


@bp.route("")
@admin_required
def index():
    page, size = page_args()
    db = get_db()
    total = db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    pager = build_pager(total, page, size)
    rows = db.execute(
        f"""SELECT * FROM users ORDER BY {sort_sql({
            'login_name': 'login_name',
            'display_name': 'display_name',
            'role': 'role',
            'status': 'status',
            'allow_rate': 'allow_rate',
            'created_at': 'created_at',
        }, 'created_at DESC, id DESC')} LIMIT ? OFFSET ?""",
        (size, pager["offset"]),
    ).fetchall()
    return render_template(
        "users.html",
        rows=rows,
        pager=pager,
        allow_manual=get_setting("allow_user_manual_edit", "0") == "1",
    )


@bp.route("/settings", methods=["POST"])
@admin_required
def settings():
    enabled = "1" if request.form.get("allow_user_manual_edit") == "1" else "0"
    db = get_db()
    begin_immediate(db)
    db.execute(
        """INSERT INTO settings (key, value) VALUES ('allow_user_manual_edit', ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (enabled,),
    )
    user = current_user()
    log_op(
        db,
        user,
        "setting_update",
        "开放普通用户手动编辑编号" if enabled == "1" else "关闭普通用户手动编辑编号",
    )
    db.commit()
    flash("手动编辑权限已更新", "success")
    return redirect(url_for("users.index"))


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new():
    user = current_user()
    form = {"login_name": "", "display_name": "", "role": "user", "allow_rate": "", "password": ""}
    errors = []
    if request.method == "POST":
        form.update(form_dict())
        db = get_db()
        try:
            data = _validate_new(db, form)
            begin_immediate(db)
            ts = now_str()
            cur = db.execute(
                """INSERT INTO users
                   (login_name, display_name, password_hash, role, status, allow_rate, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'active', ?, ?, ?)""",
                (
                    data["login_name"],
                    data["display_name"],
                    generate_password_hash(data["password"]),
                    data["role"],
                    data["allow_rate"],
                    ts,
                    ts,
                ),
            )
            log_op(db, user, "user_create", f"新增用户 {data['login_name']}（{data['display_name']}）", "user", cur.lastrowid)
            db.commit()
            flash("用户已新增", "success")
            return redirect(url_for("users.index"))
        except ValueError as exc:
            safe_rollback(db)
            errors = [str(exc)]
        except Exception:
            safe_rollback(db)
            errors = ["保存失败，请重试"]
    return render_template("user_form.html", form=form, errors=errors, editing=False)


@bp.route("/<int:uid>/edit", methods=["GET", "POST"])
@admin_required
def edit(uid):
    actor = current_user()
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        abort(404)
    form = {
        "login_name": row["login_name"],
        "display_name": row["display_name"],
        "role": row["role"],
        "status": row["status"],
        "allow_rate": "1" if row["allow_rate"] else "",
        "password": "",
    }
    errors = []
    if request.method == "POST":
        posted = form_dict()
        form["display_name"] = posted.get("display_name", "")
        form["role"] = posted.get("role", "")
        form["status"] = posted.get("status", "")
        form["allow_rate"] = posted.get("allow_rate", "")
        form["password"] = posted.get("password", "")
        try:
            data = _validate_edit(db, row, form, actor)
            begin_immediate(db)
            ts = now_str()
            if data["password"]:
                db.execute(
                    """UPDATE users
                       SET display_name=?, role=?, status=?, allow_rate=?, password_hash=?, updated_at=?
                       WHERE id=?""",
                    (
                        data["display_name"],
                        data["role"],
                        data["status"],
                        data["allow_rate"],
                        generate_password_hash(data["password"]),
                        ts,
                        uid,
                    ),
                )
                log_op(db, actor, "password_reset", f"重置用户 {row['login_name']} 的密码", "user", uid)
            else:
                db.execute(
                    """UPDATE users SET display_name=?, role=?, status=?, allow_rate=?, updated_at=?
                       WHERE id=?""",
                    (data["display_name"], data["role"], data["status"], data["allow_rate"], ts, uid),
                )
            log_op(db, actor, "user_update", f"修改用户 {row['login_name']}", "user", uid)
            db.commit()
            flash("用户已保存", "success")
            return redirect(url_for("users.index"))
        except ValueError as exc:
            safe_rollback(db)
            errors = [str(exc)]
        except Exception:
            safe_rollback(db)
            errors = ["保存失败，请重试"]
    return render_template("user_form.html", form=form, errors=errors, editing=True, record=row)


@bp.route("/batch-delete", methods=["POST"])
@admin_required
def batch_delete():
    actor = current_user()
    ids = [int(item) for item in request.form.getlist("ids") if str(item).isdigit()]
    if not ids:
        flash("请先选择用户", "error")
        return redirect(url_for("users.index"))
    db = get_db()
    done = 0
    skipped = 0
    try:
        begin_immediate(db)
        for uid in ids[:200]:
            row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not row:
                skipped += 1
                continue
            if row["id"] == actor["id"]:
                skipped += 1
                continue
            if row["role"] == "admin" and row["status"] == "active" and _admin_count(db) <= 1:
                skipped += 1
                continue
            db.execute("DELETE FROM users WHERE id=?", (uid,))
            log_op(db, actor, "user_delete", f"删除用户 {row['login_name']}", "user", uid)
            done += 1
        db.commit()
    except Exception:
        safe_rollback(db)
        flash("删除失败，请重试", "error")
        return redirect(url_for("users.index"))
    message = f"已删除 {done} 个用户"
    if skipped:
        message += f"，跳过 {skipped} 个（当前登录账号、最后一名管理员或已不存在）"
    flash(message, "success" if done else "error")
    return redirect(url_for("users.index"))


def _validate_new(db, form):
    login_name = validate_login_name(form.get("login_name"))
    display_name = clean_text(form.get("display_name"), 32, "显示名", required=True)
    role = form.get("role") or ""
    if role not in ("admin", "user", "viewer"):
        raise ValueError("请选择角色")
    password = form.get("password") or ""
    if len(password) < 6 or len(password) > 64:
        raise ValueError("密码长度需为 6 到 64 位")
    if db.execute("SELECT id FROM users WHERE login_name=?", (login_name,)).fetchone():
        raise ValueError("登录名已存在")
    return {
        "login_name": login_name,
        "display_name": display_name,
        "role": role,
        "password": password,
        "allow_rate": 1 if form.get("allow_rate") == "1" else 0,
    }


def _validate_edit(db, row, form, actor):
    display_name = clean_text(form.get("display_name"), 32, "显示名", required=True)
    role = form.get("role") or ""
    status = form.get("status") or ""
    if role not in ("admin", "user", "viewer"):
        raise ValueError("请选择角色")
    if status not in ("active", "disabled"):
        raise ValueError("请选择状态")
    password = form.get("password") or ""
    if password and (len(password) < 6 or len(password) > 64):
        raise ValueError("密码长度需为 6 到 64 位")
    if row["id"] == actor["id"] and status != "active":
        raise ValueError("不能禁用当前登录的管理员")
    if row["role"] == "admin" and row["status"] == "active":
        if role != "admin" or status != "active":
            if _admin_count(db, except_id=row["id"]) < 1:
                raise ValueError("至少保留一名启用的系统管理员")
    return {
        "display_name": display_name,
        "role": role,
        "status": status,
        "password": password,
        "allow_rate": 1 if form.get("allow_rate") == "1" else 0,
    }
