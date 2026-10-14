from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.auth import can_rate, current_user, login_required
from app.db import begin_immediate, get_db, log_op, safe_rollback
from app.utils import build_pager, clean_text, current_month, form_dict, now_str, page_args, parse_date, parse_decimal, parse_month, sort_sql
from decimal import Decimal

bp = Blueprint("rates", __name__, url_prefix="/rates")


def _blank():
    return {
        "month": current_month(),
        "rate": "",
        "effective_date": "",
        "remark": "",
    }


def _validate(db, form, current_id=None):
    month = parse_month(form.get("month"), "月份", required=True)
    rate = parse_decimal(form.get("rate"), 6, "汇率", required=True)
    if Decimal(rate) <= 0:
        raise ValueError("汇率必须大于 0")
    effective = parse_date(form.get("effective_date"), "生效日期", required=True)
    remark = clean_text(form.get("remark"), 200, "备注", required=False)
    sql = "SELECT id FROM exchange_rates WHERE month=?"
    params = [month]
    if current_id:
        sql += " AND id!=?"
        params.append(current_id)
    if db.execute(sql, params).fetchone():
        raise ValueError("该月份汇率已存在，请直接修改")
    return {
        "month": month,
        "rate": rate,
        "effective_date": effective,
        "remark": remark,
    }


@bp.route("")
@login_required
def index():
    page, size = page_args()
    db = get_db()
    total = db.execute("SELECT COUNT(*) AS n FROM exchange_rates").fetchone()["n"]
    pager = build_pager(total, page, size)
    rows = db.execute(
        f"""SELECT * FROM exchange_rates ORDER BY {sort_sql({
            'month': 'month',
            'source_currency': 'source_currency',
            'target_currency': 'target_currency',
            'rate': 'CAST(rate AS REAL)',
            'effective_date': 'effective_date',
            'maintainer_name': 'maintainer_name',
            'remark': 'remark',
        }, 'created_at DESC, month DESC, id DESC')} LIMIT ? OFFSET ?""",
        (size, pager["offset"]),
    ).fetchall()
    return render_template("rates.html", rows=rows, pager=pager)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    user = current_user()
    if not can_rate(user):
        abort(403)
    form = _blank()
    errors = []
    if request.method == "POST":
        form.update(form_dict())
        db = get_db()
        try:
            data = _validate(db, form)
            begin_immediate(db)
            ts = now_str()
            cur = db.execute(
                """INSERT INTO exchange_rates
                   (month, source_currency, target_currency, rate, effective_date,
                    maintainer_id, maintainer_name, remark, created_at, updated_at)
                   VALUES (?, 'USD', 'CNY', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["month"],
                    data["rate"],
                    data["effective_date"],
                    user["id"],
                    user["display_name"],
                    data["remark"] or None,
                    ts,
                    ts,
                ),
            )
            log_op(
                db,
                user,
                "rate_create",
                f"维护汇率 {data['month']} = {data['rate']}",
                "rate",
                cur.lastrowid,
                data,
            )
            db.commit()
            flash("汇率已保存", "success")
            return redirect(url_for("rates.index"))
        except ValueError as exc:
            safe_rollback(db)
            errors = [str(exc)]
        except Exception:
            safe_rollback(db)
            errors = ["保存失败，请重试"]
    return render_template("rate_form.html", form=form, errors=errors, editing=False)


@bp.route("/<int:rid>/edit", methods=["GET", "POST"])
@login_required
def edit(rid):
    user = current_user()
    if not can_rate(user):
        abort(403)
    db = get_db()
    row = db.execute("SELECT * FROM exchange_rates WHERE id=?", (rid,)).fetchone()
    if not row:
        abort(404)
    form = {
        "month": row["month"],
        "rate": row["rate"],
        "effective_date": row["effective_date"],
        "remark": row["remark"] or "",
    }
    errors = []
    if request.method == "POST":
        form.update(form_dict())
        try:
            data = _validate(db, form, current_id=rid)
            begin_immediate(db)
            ts = now_str()
            db.execute(
                """UPDATE exchange_rates
                   SET month=?, rate=?, effective_date=?, remark=?, maintainer_id=?,
                       maintainer_name=?, updated_at=?
                   WHERE id=?""",
                (
                    data["month"],
                    data["rate"],
                    data["effective_date"],
                    data["remark"] or None,
                    user["id"],
                    user["display_name"],
                    ts,
                    rid,
                ),
            )
            log_op(db, user, "rate_update", f"修改汇率 {data['month']} = {data['rate']}", "rate", rid, data)
            db.commit()
            flash("汇率已更新", "success")
            return redirect(url_for("rates.index"))
        except ValueError as exc:
            safe_rollback(db)
            errors = [str(exc)]
        except Exception:
            safe_rollback(db)
            errors = ["保存失败，请重试"]
    return render_template("rate_form.html", form=form, errors=errors, editing=True, record=row)


@bp.route("/batch-delete", methods=["POST"])
@login_required
def batch_delete():
    user = current_user()
    if not can_rate(user):
        abort(403)
    ids = [int(item) for item in request.form.getlist("ids") if str(item).isdigit()]
    if not ids:
        flash("请先选择汇率", "error")
        return redirect(url_for("rates.index"))
    db = get_db()
    done = 0
    try:
        begin_immediate(db)
        for rid in ids[:200]:
            row = db.execute("SELECT * FROM exchange_rates WHERE id=?", (rid,)).fetchone()
            if not row:
                continue
            db.execute("DELETE FROM exchange_rates WHERE id=?", (rid,))
            log_op(db, user, "rate_delete", f"删除汇率 {row['month']}", "rate", rid)
            done += 1
        db.commit()
    except Exception:
        safe_rollback(db)
        flash("删除失败，请重试", "error")
        return redirect(url_for("rates.index"))
    flash(f"已删除 {done} 条汇率" if done else "没有可删除的汇率", "success" if done else "error")
    return redirect(url_for("rates.index"))
