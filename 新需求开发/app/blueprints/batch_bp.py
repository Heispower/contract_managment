from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.auth import can_mutate, current_user, login_required
from app.blueprints.invoice_bp import delete_batch_tree, sub_summary
from app.db import begin_immediate, get_db, safe_rollback
from app.utils import add_months, build_pager, like, page_args, sort_sql
from datetime import datetime

bp = Blueprint("batches", __name__, url_prefix="/batches")


@bp.route("")
@login_required
def index():
    page, size = page_args()
    args = request.args
    where = ["b.deleted_at IS NULL"]
    params = []
    if (args.get("prefix") or "").strip():
        where.append("b.prefix LIKE ? ESCAPE '\\'")
        params.append(like(args.get("prefix").strip()))
    if args.get("number_rule") in ("铝矿海运", "铝矿空运", "锰矿"):
        where.append("b.number_rule=?")
        params.append(args.get("number_rule"))
    scope = args.get("scope") or "recent"
    if scope != "all":
        cutoff = add_months(datetime.now(), -3).strftime("%Y-%m-%d %H:%M:%S")
        where.append("b.created_at>=?")
        params.append(cutoff)
    sql_where = " AND ".join(where)
    db = get_db()
    total = db.execute(
        f"SELECT COUNT(*) AS n FROM batches b WHERE {sql_where}",
        params,
    ).fetchone()["n"]
    pager = build_pager(total, page, size)
    rows = db.execute(
        f"""SELECT b.* FROM batches b WHERE {sql_where}
            ORDER BY {sort_sql({
                'prefix': 'b.prefix',
                'created_at': 'b.created_at',
                'biz_rule': "b.business_type || '/' || b.number_rule",
                'transport_type': 'b.transport_type',
                'used': "(SELECT COUNT(*) FROM batch_slots s WHERE s.batch_id=b.id AND s.status='used')",
                'free': "(SELECT COUNT(*) FROM batch_slots s WHERE s.batch_id=b.id AND s.status='free')",
            }, 'b.number_year DESC, IFNULL(b.num_seq, 0) DESC, b.created_at DESC, b.id DESC', 'b.id DESC')} LIMIT ? OFFSET ?""",
        [*params, size, pager["offset"]],
    ).fetchall()
    summaries = {row["id"]: sub_summary(db, row["id"]) for row in rows}
    return render_template(
        "batches.html",
        rows=rows,
        pager=pager,
        filters=args,
        summaries=summaries,
        scope=scope,
    )


@bp.route("/<int:bid>/delete", methods=["POST"])
@login_required
def delete(bid):
    user = current_user()
    db = get_db()
    try:
        begin_immediate(db)
        batch = db.execute(
            "SELECT * FROM batches WHERE id=? AND deleted_at IS NULL",
            (bid,),
        ).fetchone()
        if not batch:
            safe_rollback(db)
            flash("批次不存在或已删除", "error")
            return redirect(url_for("batches.index"))
        if not can_mutate(user, batch):
            safe_rollback(db)
            flash("只能删除自己创建的批次", "error")
            return redirect(url_for("batches.index"))
        others = db.execute(
            """SELECT id, created_by FROM invoices
               WHERE batch_id=? AND deleted_at IS NULL AND created_by!=?""",
            (bid, user["id"]),
        ).fetchall()
        if user["role"] != "admin" and others:
            safe_rollback(db)
            flash("批次中包含其他用户登记的发票，请联系管理员删除", "error")
            return redirect(url_for("batches.index"))
        delete_batch_tree(db, batch, user)
        db.commit()
        flash(f"已删除批次 {batch['prefix']}，前缀和小批号已回收", "success")
    except Exception:
        safe_rollback(db)
        import logging

        logging.getLogger("invoiceapp").exception("delete batch failed")
        flash("删除失败，请重试", "error")
    return redirect(url_for("batches.index"))


@bp.route("/batch-delete", methods=["POST"])
@login_required
def batch_delete():
    user = current_user()
    if user["role"] == "viewer":
        abort(403)
    ids = [int(item) for item in request.form.getlist("ids") if str(item).isdigit()]
    if not ids:
        flash("请先选择批次", "error")
        return redirect(url_for("batches.index"))
    db = get_db()
    done = 0
    skipped = 0
    try:
        begin_immediate(db)
        for bid in ids[:200]:
            batch = db.execute(
                "SELECT * FROM batches WHERE id=? AND deleted_at IS NULL",
                (bid,),
            ).fetchone()
            if not batch or not can_mutate(user, batch):
                skipped += 1
                continue
            others = db.execute(
                """SELECT id FROM invoices
                   WHERE batch_id=? AND deleted_at IS NULL AND created_by!=?""",
                (bid, user["id"]),
            ).fetchall()
            if user["role"] != "admin" and others:
                skipped += 1
                continue
            delete_batch_tree(db, batch, user)
            done += 1
        db.commit()
    except Exception:
        safe_rollback(db)
        import logging

        logging.getLogger("invoiceapp").exception("batch delete batches failed")
        flash("删除失败，请重试", "error")
        return redirect(url_for("batches.index"))
    message = f"已删除 {done} 个批次，前缀和小批号已回收"
    if skipped:
        message += f"，跳过 {skipped} 条（无权限、已删除或批次内含他人发票）"
    flash(message, "success" if done else "error")
    return redirect(url_for("batches.index"))
