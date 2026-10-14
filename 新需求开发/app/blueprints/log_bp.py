from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.auth import admin_required, current_user
from app.db import begin_immediate, get_db, log_op, safe_rollback
from app.utils import build_pager, like, page_args, sort_sql

bp = Blueprint("logs", __name__, url_prefix="/logs")

ACTION_LABELS = {
    "login": "登录",
    "login_fail": "登录失败",
    "logout": "退出",
    "password_change": "修改本人密码",
    "password_reset": "重置用户密码",
    "contract_import": "批量导入合同",
    "contract_create": "新增合同",
    "contract_update": "编辑合同",
    "contract_delete": "删除合同",
    "invoice_import": "批量导入发票",
    "invoice_create": "新增发票",
    "invoice_update": "编辑发票",
    "invoice_delete": "删除发票",
    "batch_delete": "删除批次",
    "number_manual_edit": "手动编辑编号",
    "rate_create": "新增汇率",
    "rate_update": "修改汇率",
    "rate_delete": "删除汇率",
    "user_create": "新增用户",
    "user_update": "修改用户",
    "user_delete": "删除用户",
    "log_delete": "删除日志",
    "setting_update": "修改系统设置",
    "seq_floor": "设定当前序号",
}


@bp.route("")
@admin_required
def index():
    tab = request.args.get("tab") or "ops"
    if tab not in ("ops", "manual"):
        tab = "ops"
    page, size = page_args()
    db = get_db()
    if tab == "manual":
        where = ["1=1"]
        params = []
        keyword = (request.args.get("keyword") or "").strip()
        if keyword:
            token = like(keyword)
            where.append(
                "(old_no LIKE ? ESCAPE '\\' OR new_no LIKE ? ESCAPE '\\' OR reason LIKE ? ESCAPE '\\' OR operator_name LIKE ? ESCAPE '\\')"
            )
            params.extend([token, token, token, token])
        if (request.args.get("date_from") or "").strip():
            where.append("created_at>=?")
            params.append(request.args.get("date_from").strip() + " 00:00:00")
        if (request.args.get("date_to") or "").strip():
            where.append("created_at<=?")
            params.append(request.args.get("date_to").strip() + " 23:59:59")
        sql_where = " AND ".join(where)
        total = db.execute(
            f"SELECT COUNT(*) AS n FROM number_edit_logs WHERE {sql_where}",
            params,
        ).fetchone()["n"]
        pager = build_pager(total, page, size)
        rows = db.execute(
            f"""SELECT * FROM number_edit_logs WHERE {sql_where}
                ORDER BY {sort_sql({
                    'created_at': 'created_at',
                    'target_type': 'target_type',
                    'old_no': 'old_no',
                    'new_no': 'new_no',
                    'reason': 'reason',
                    'operator_name': 'operator_name',
                }, 'created_at DESC, id DESC')} LIMIT ? OFFSET ?""",
            [*params, size, pager["offset"]],
        ).fetchall()
        return render_template(
            "logs.html",
            tab=tab,
            rows=rows,
            pager=pager,
            filters=request.args,
            actions=ACTION_LABELS,
        )
    where = ["1=1"]
    params = []
    keyword = (request.args.get("keyword") or "").strip()
    if keyword:
        token = like(keyword)
        where.append("(summary LIKE ? ESCAPE '\\' OR IFNULL(display_name,'') LIKE ? ESCAPE '\\' OR IFNULL(login_name,'') LIKE ? ESCAPE '\\')")
        params.extend([token, token, token])
    action = (request.args.get("action") or "").strip()
    if action in ACTION_LABELS:
        where.append("action=?")
        params.append(action)
    if (request.args.get("date_from") or "").strip():
        where.append("created_at>=?")
        params.append(request.args.get("date_from").strip() + " 00:00:00")
    if (request.args.get("date_to") or "").strip():
        where.append("created_at<=?")
        params.append(request.args.get("date_to").strip() + " 23:59:59")
    sql_where = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) AS n FROM operation_logs WHERE {sql_where}", params).fetchone()["n"]
    pager = build_pager(total, page, size)
    rows = db.execute(
        f"""SELECT * FROM operation_logs WHERE {sql_where}
            ORDER BY {sort_sql({
                'created_at': 'created_at',
                'display_name': 'display_name',
                'action': 'action',
                'summary': 'summary',
            }, 'created_at DESC, id DESC')} LIMIT ? OFFSET ?""",
        [*params, size, pager["offset"]],
    ).fetchall()
    return render_template(
        "logs.html",
        tab=tab,
        rows=rows,
        pager=pager,
        filters=request.args,
        actions=ACTION_LABELS,
    )


@bp.route("/batch-delete", methods=["POST"])
@admin_required
def batch_delete():
    tab = request.args.get("tab") or request.form.get("tab") or "ops"
    if tab not in ("ops", "manual"):
        tab = "ops"
    ids = [int(item) for item in request.form.getlist("ids") if str(item).isdigit()]
    if not ids:
        flash("请先选择日志", "error")
        return redirect(url_for("logs.index", tab=tab))
    table = "number_edit_logs" if tab == "manual" else "operation_logs"
    db = get_db()
    try:
        begin_immediate(db)
        done = 0
        for item_id in ids[:200]:
            cur = db.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
            done += cur.rowcount
        log_op(
            db,
            current_user(),
            "log_delete",
            f"删除{'编号手动编辑' if tab == 'manual' else '操作'}日志 {done} 条",
        )
        db.commit()
    except Exception:
        safe_rollback(db)
        flash("删除失败，请重试", "error")
        return redirect(url_for("logs.index", tab=tab))
    flash(f"已删除 {done} 条日志", "success" if done else "error")
    return redirect(url_for("logs.index", tab=tab))
