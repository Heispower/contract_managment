from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.auth import admin_required, current_user
from app.db import begin_immediate, get_db, log_op, safe_rollback
from app.numbering import (
    POOL_LABELS,
    format_number,
    parse_floor_value,
    pool_floor,
    preview_number,
    set_pool_floor,
)
from app.utils import default_number_year

bp = Blueprint("sequences", __name__, url_prefix="/sequences")

POOL_ORDER = (
    "contract_mn",
    "contract_al",
    "invoice_mn",
    "invoice_al_sea",
    "invoice_al_air",
)


def _rows(db, year):
    rows = []
    for pool in POOL_ORDER:
        floor = pool_floor(db, pool)
        used = db.execute(
            """SELECT COALESCE(MAX(seq), 0) AS m FROM number_slots
               WHERE pool_key=? AND status='used'""",
            (pool,),
        ).fetchone()["m"]
        try:
            nxt = preview_number(db, pool, year)
        except ValueError:
            nxt = None
        rows.append({
            "pool": pool,
            "label": POOL_LABELS[pool],
            "floor": floor,
            "floor_no": format_number(pool, year, floor) if floor else "",
            "used": int(used),
            "used_no": format_number(pool, year, used) if used else "",
            "next_no": nxt["number"] if nxt else "",
            "sample": format_number(pool, year, max(floor + 1, 1)),
        })
    return rows


@bp.route("", methods=["GET", "POST"])
@admin_required
def index():
    db = get_db()
    year = default_number_year()
    if request.method == "POST":
        pool = (request.form.get("pool") or "").strip()
        if pool not in POOL_LABELS:
            abort(400)
        user = current_user()
        try:
            begin_immediate(db)
            old = pool_floor(db, pool)
            if request.form.get("clear") == "1":
                seq = 0
            else:
                seq = parse_floor_value(pool, request.form.get("latest"))
            set_pool_floor(db, pool, seq)
            if seq:
                summary = f"{POOL_LABELS[pool]} 历史序号划到 {seq}，自动编号从下一个号开始"
            else:
                summary = f"{POOL_LABELS[pool]} 已取消历史序号，自动编号从空闲号重新开始"
            log_op(db, user, "seq_floor", summary, "number_pool", None, {"原序号": old, "新序号": seq})
            db.commit()
        except ValueError as exc:
            safe_rollback(db)
            flash(str(exc), "error")
            return render_template("sequences.html", rows=_rows(db, year), year=year)
        except Exception:
            safe_rollback(db)
            flash("保存失败，请重试", "error")
            return redirect(url_for("sequences.index"))
        flash(summary, "success")
        return redirect(url_for("sequences.index"))
    return render_template("sequences.html", rows=_rows(db, year), year=year)
