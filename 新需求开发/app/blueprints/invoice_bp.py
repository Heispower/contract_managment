from datetime import datetime
from io import BytesIO

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from openpyxl import Workbook

from app.auth import can_manual, can_mutate, can_write, current_user, login_required
from app.blueprints.contract_bp import CONTRACT_RECENT, _style_sheet
from app.db import begin_immediate, get_db, log_op, safe_rollback
from app.importer import handle_import_request, import_page, template_bytes
from app.numbering import (
    RULE_POOL,
    allocate_number,
    allocate_sub,
    matches_any_pattern,
    number_exists,
    occupy_slot,
    parse_pool_number,
    preview_number,
    preview_sub,
    release_number,
    release_sub,
    slot_blocked,
)
from app.utils import (
    add_months,
    build_pager,
    clean_text,
    current_month,
    default_number_year,
    excel_text,
    sort_sql,
    form_dict,
    like,
    money_div,
    money_mul,
    batch_amount_totals,
    now_str,
    refresh_batch_amounts,
    refresh_open_batch_amounts,
    page_args,
    parse_date,
    parse_decimal,
    parse_month,
    year_options,
)
from decimal import Decimal

bp = Blueprint("invoices", __name__, url_prefix="/invoices")

INVOICE_SORT = {
    "invoice_no": "i.invoice_no",
    "contract_no": "c.contract_no",
    "content": "i.content",
    "bl_date": "i.bl_date",
    "price_term": "i.price_term",
    "currency": "i.currency",
    "amount_usd": "CAST(i.amount_usd AS REAL)",
    "amount_cny": "CAST(i.amount_cny AS REAL)",
    "exchange_rate": "CAST(i.exchange_rate AS REAL)",
    "po_no": "i.po_no",
    "operator_name": "i.operator_name",
    "transport_type": "i.transport_type",
    "email_sent_date": "i.email_sent_date",
    "remark": "i.remark",
    "bl_no": "i.bl_no",
    "is_batch": "i.is_batch",
    "batch_prefix": "i.batch_prefix",
    "batch_sub_no": "i.batch_sub_no",
}
INVOICE_RECENT = (
    "i.number_year DESC, IFNULL(i.num_seq, 0) DESC, IFNULL(i.sub_seq, 0) DESC, "
    "i.created_at DESC, i.id DESC"
)

RULES = ("铝矿海运", "铝矿空运", "锰矿")


def _filters():
    args = request.args
    where = ["i.deleted_at IS NULL"]
    params = []
    keyword = (args.get("keyword") or "").strip()
    if keyword:
        token = like(keyword)
        where.append(
            """(i.invoice_no LIKE ? ESCAPE '\\' OR i.content LIKE ? ESCAPE '\\'
                OR IFNULL(i.po_no,'') LIKE ? ESCAPE '\\' OR i.operator_name LIKE ? ESCAPE '\\'
                OR IFNULL(i.bl_no,'') LIKE ? ESCAPE '\\' OR IFNULL(i.remark,'') LIKE ? ESCAPE '\\'
                OR IFNULL(i.batch_prefix,'') LIKE ? ESCAPE '\\' OR IFNULL(c.contract_no,'') LIKE ? ESCAPE '\\')"""
        )
        params.extend([token] * 8)
    for key, column in (
        ("invoice_no", "i.invoice_no"),
        ("content", "i.content"),
        ("po_no", "i.po_no"),
        ("operator_name", "i.operator_name"),
        ("bl_no", "i.bl_no"),
        ("batch_prefix", "i.batch_prefix"),
    ):
        value = (args.get(key) or "").strip()
        if value:
            where.append(f"IFNULL({column},'') LIKE ? ESCAPE '\\'")
            params.append(like(value))
    contract_no = (args.get("contract_no") or "").strip()
    if contract_no:
        where.append("IFNULL(c.contract_no,'') LIKE ? ESCAPE '\\'")
        params.append(like(contract_no))
    if args.get("number_rule") in RULES:
        where.append("i.number_rule=?")
        params.append(args.get("number_rule"))
    if args.get("transport_type") in ("海运", "空运"):
        where.append("i.transport_type=?")
        params.append(args.get("transport_type"))
    if args.get("is_batch") in ("0", "1"):
        where.append("i.is_batch=?")
        params.append(int(args.get("is_batch")))
    if (args.get("email_from") or "").strip():
        where.append("IFNULL(i.email_sent_date,'')>=?")
        params.append(args.get("email_from").strip())
    if (args.get("email_to") or "").strip():
        where.append("IFNULL(i.email_sent_date,'')<=?")
        params.append(args.get("email_to").strip())
    return " AND ".join(where), params


def _blank_form():
    return {
        "mode": "normal",
        "batch_id": "",
        "contract_id": "",
        "business_type": "锰矿",
        "number_rule": "锰矿",
        "number_year": str(default_number_year()),
        "content": "",
        "bl_date": "",
        "price_term": "FOB",
        "currency": "USD",
        "amount_usd": "",
        "amount_cny": "",
        "exchange_month": current_month(),
        "exchange_rate": "",
        "po_no": "",
        "transport_type": "海运",
        "email_sent_date": "",
        "remark": "",
        "bl_no": "",
    }


def _form_from_row(row):
    return {
        "mode": "edit",
        "batch_id": row["batch_id"] or "",
        "contract_id": row["contract_id"] or "",
        "business_type": row["business_type"],
        "number_rule": row["number_rule"],
        "number_year": str(row["number_year"]),
        "content": row["content"],
        "bl_date": row["bl_date"] or "",
        "price_term": row["price_term"],
        "currency": row["currency"],
        "amount_usd": row["amount_usd"],
        "amount_cny": row["amount_cny"],
        "exchange_month": row["exchange_month"],
        "exchange_rate": row["exchange_rate"],
        "po_no": row["po_no"] or "",
        "transport_type": row["transport_type"],
        "email_sent_date": row["email_sent_date"] or "",
        "remark": row["remark"] or "",
        "bl_no": row["bl_no"] or "",
    }


def _official_rate(db, month):
    return db.execute("SELECT * FROM exchange_rates WHERE month=?", (month,)).fetchone()


def recent_batches(db):
    cutoff = add_months(datetime.now(), -3).strftime("%Y-%m-%d %H:%M:%S")
    return db.execute(
        """SELECT * FROM batches
           WHERE deleted_at IS NULL AND created_at>=?
           ORDER BY number_year DESC, IFNULL(num_seq, 0) DESC, created_at DESC, id DESC""",
        (cutoff,),
    ).fetchall()


def _load_contract(db, contract_id):
    if contract_id in ("", None):
        return None
    if not str(contract_id).isdigit():
        raise ValueError("关联合同无效")
    row = db.execute(
        "SELECT * FROM contracts WHERE id=? AND deleted_at IS NULL",
        (int(contract_id),),
    ).fetchone()
    if not row:
        raise ValueError("关联合同不存在")
    return row


def _assert_rule(business_type, transport_type, number_rule):
    if number_rule not in RULES:
        raise ValueError("请选择编号规则")
    if transport_type not in ("海运", "空运"):
        raise ValueError("请选择运输方式")
    if business_type not in ("锰矿", "铝矿"):
        raise ValueError("请选择业务类型")
    if number_rule == "锰矿" and business_type != "锰矿":
        raise ValueError("锰矿编号规则只能用于锰矿业务")
    if number_rule == "铝矿海运" and (business_type != "铝矿" or transport_type != "海运"):
        raise ValueError("铝矿海运编号需要业务类型为铝矿且运输方式为海运")
    if number_rule == "铝矿空运" and (business_type != "铝矿" or transport_type != "空运"):
        raise ValueError("铝矿空运编号需要业务类型为铝矿且运输方式为空运")


def _amounts(form, official, allow_zero=False):
    month = parse_month(form.get("exchange_month"), "汇率月份", required=True)
    posted = (form.get("exchange_rate") or "").strip()
    official_rate = official["rate"] if official else ""
    usd = parse_decimal(form.get("amount_usd"), 2, "美元金额", required=False)
    cny = parse_decimal(form.get("amount_cny"), 2, "人民币金额", required=False)
    zero_only = (not usd or Decimal(usd) == 0) and (not cny or Decimal(cny) == 0)
    if not usd and not cny and not allow_zero:
        raise ValueError("请填写美元金额或人民币金额")
    if allow_zero and zero_only and not posted and not official_rate:
        return {
            "exchange_month": month,
            "exchange_rate": "0.000000",
            "rate_adjusted": 0,
            "amount_usd": "0.00",
            "amount_cny": "0.00",
            "official_missing": True,
        }
    if not posted:
        if not official_rate:
            raise ValueError("当月尚未维护汇率，请先到汇率维护录入，或在本页手工填写汇率")
        rate = official_rate
        adjusted = 0
    else:
        rate = parse_decimal(posted, 6, "汇率", required=True)
        if Decimal(rate) <= 0:
            raise ValueError("汇率必须大于 0")
        if not official_rate or Decimal(rate) != Decimal(official_rate):
            adjusted = 1
        else:
            adjusted = 0
    if not usd and not cny:
        usd, cny = "0.00", "0.00"
    elif usd and not cny:
        cny = money_mul(usd, rate)
    elif cny and not usd:
        usd = money_div(cny, rate)
    return {
        "exchange_month": month,
        "exchange_rate": rate,
        "rate_adjusted": adjusted,
        "amount_usd": usd,
        "amount_cny": cny,
        "official_missing": not official_rate,
    }


def _common(db, form, allow_zero=False):
    price_term = form.get("price_term") or ""
    currency = form.get("currency") or ""
    if price_term not in ("CIF", "FOB"):
        raise ValueError("请选择价格条款")
    if currency not in ("CNY", "USD"):
        raise ValueError("请选择结算币种")
    contract = _load_contract(db, (form.get("contract_id") or "").strip())
    month = (form.get("exchange_month") or "").strip() or current_month()
    official = _official_rate(db, month) if len(month) == 7 else None
    amounts = _amounts(form, official, allow_zero=allow_zero)
    return {
        "contract_id": None if contract is None else contract["id"],
        "content": clean_text(form.get("content"), 500, "所含内容", required=True),
        "bl_date": parse_date(form.get("bl_date"), "提单日期", required=False),
        "price_term": price_term,
        "currency": currency,
        "po_no": clean_text(form.get("po_no"), 100, "PO", required=False),
        "email_sent_date": parse_date(form.get("email_sent_date"), "发邮件时间", required=False),
        "remark": clean_text(form.get("remark"), 500, "备注", required=False),
        "bl_no": clean_text(form.get("bl_no"), 100, "提单号", required=False),
        **amounts,
    }


def _validate_create(db, form):
    mode = form.get("mode") or "normal"
    if mode not in ("normal", "new_batch", "join_batch"):
        raise ValueError("请选择发票编号方式")
    data = _common(db, form, allow_zero=mode in ("new_batch", "join_batch"))
    data["mode"] = mode
    if mode == "join_batch":
        batch_id = (form.get("batch_id") or "").strip()
        if not batch_id.isdigit():
            raise ValueError("请选择批次发货")
        batch = _joinable_batch(db, int(batch_id))
        data["batch"] = batch
        data["business_type"] = batch["business_type"]
        data["number_rule"] = batch["number_rule"]
        data["number_year"] = batch["number_year"]
        data["transport_type"] = batch["transport_type"]
        return data
    business_type = form.get("business_type") or ""
    transport_type = form.get("transport_type") or ""
    number_rule = form.get("number_rule") or ""
    _assert_rule(business_type, transport_type, number_rule)
    year_text = (form.get("number_year") or "").strip()
    if not year_text.isdigit():
        raise ValueError("请选择编号年份")
    year = int(year_text)
    if year < 2000 or year > 2099:
        raise ValueError("编号年份需在 2000 到 2099 之间")
    data.update(
        {
            "business_type": business_type,
            "transport_type": transport_type,
            "number_rule": number_rule,
            "number_year": year,
        }
    )
    return data


def _joinable_batch(db, batch_id):
    batch = db.execute(
        "SELECT * FROM batches WHERE id=? AND deleted_at IS NULL",
        (batch_id,),
    ).fetchone()
    if not batch:
        raise ValueError("批次不存在或已删除")
    cutoff = add_months(datetime.now(), -3).strftime("%Y-%m-%d %H:%M:%S")
    if batch["created_at"] < cutoff:
        raise ValueError("批次发货只能选择近 3 个月生成的批次号")
    return batch


@bp.route("")
@login_required
def index():
    page, size = page_args()
    where, params = _filters()
    db = get_db()
    refresh_open_batch_amounts(db)
    total = db.execute(
        f"""SELECT COUNT(*) AS n FROM invoices i
            LEFT JOIN contracts c ON c.id=i.contract_id
            WHERE {where}""",
        params,
    ).fetchone()["n"]
    pager = build_pager(total, page, size)
    rows = db.execute(
        f"""SELECT i.*, c.contract_no
            FROM invoices i
            LEFT JOIN contracts c ON c.id=i.contract_id
            WHERE {where}
            ORDER BY {sort_sql(INVOICE_SORT, INVOICE_RECENT, 'i.id DESC')}
            LIMIT ? OFFSET ?""",
        [*params, size, pager["offset"]],
    ).fetchall()
    return render_template("invoices.html", rows=rows, pager=pager, filters=request.args)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    user = current_user()
    if not can_write(user):
        abort(403)
    db = get_db()
    form = _blank_form()
    errors = []
    if request.method == "POST":
        form.update(form_dict())
        try:
            data = _validate_create(db, form)
            begin_immediate(db)
            result = _insert_invoice(db, data, user)
            db.commit()
            message = f"已生成发票号 {result['invoice_no']}"
            if result["reused"]:
                message += "，已复用空闲编号"
            flash(message, "success")
            return redirect(url_for("invoices.index"))
        except ValueError as exc:
            safe_rollback(db)
            errors = [str(exc)]
        except Exception:
            safe_rollback(db)
            _logger().exception("create invoice failed")
            errors = ["保存失败，请重试"]
    official = _official_rate(db, (form.get("exchange_month") or current_month()))
    if official and not (form.get("exchange_rate") or "").strip() and request.method == "GET":
        form["exchange_rate"] = official["rate"]
    selected = None
    if str(form.get("contract_id") or "").isdigit():
        selected = db.execute(
            "SELECT * FROM contracts WHERE id=? AND deleted_at IS NULL",
            (int(form["contract_id"]),),
        ).fetchone()
    return render_template(
        "invoice_form.html",
        form=form,
        errors=errors,
        editing=False,
        record=None,
        years=year_options(),
        batches=recent_batches(db),
        official=official,
        selected=selected,
    )


@bp.route("/<int:iid>/edit", methods=["GET", "POST"])
@login_required
def edit(iid):
    user = current_user()
    db = get_db()
    row = _alive(db, iid)
    if not can_mutate(user, row):
        abort(403)
    if row["batch_id"]:
        refresh_batch_amounts(db, row["batch_id"])
        row = _alive(db, iid)
    form = _form_from_row(row)
    errors = []
    if request.method == "POST":
        posted = form_dict()
        for key in (
            "contract_id",
            "content",
            "bl_date",
            "price_term",
            "currency",
            "amount_usd",
            "amount_cny",
            "exchange_month",
            "exchange_rate",
            "po_no",
            "email_sent_date",
            "remark",
            "bl_no",
        ):
            form[key] = posted.get(key, "")
        try:
            data = _common(db, form, allow_zero=bool(row["is_batch"]))
            begin_immediate(db)
            ts = now_str()
            fresh = _alive(db, iid)
            db.execute(
                """UPDATE invoices SET
                   contract_id=?, content=?, bl_date=?, price_term=?, currency=?,
                   amount_usd=?, amount_cny=?, exchange_rate=?, exchange_month=?,
                   rate_adjusted=?, po_no=?, email_sent_date=?, remark=?, bl_no=?,
                   updated_by=?, updated_at=?
                   WHERE id=? AND deleted_at IS NULL""",
                (
                    data["contract_id"],
                    data["content"],
                    data["bl_date"] or None,
                    data["price_term"],
                    data["currency"],
                    data["amount_usd"],
                    data["amount_cny"],
                    data["exchange_rate"],
                    data["exchange_month"],
                    data["rate_adjusted"],
                    data["po_no"] or None,
                    data["email_sent_date"] or None,
                    data["remark"] or None,
                    data["bl_no"] or None,
                    user["id"],
                    ts,
                    iid,
                ),
            )
            detail = {"发票号": fresh["invoice_no"]}
            if data["rate_adjusted"]:
                detail["汇率已手工调整"] = data["exchange_rate"]
                detail["汇率月份"] = data["exchange_month"]
            log_op(db, user, "invoice_update", f"编辑发票 {fresh['invoice_no']}", "invoice", iid, detail)
            if fresh["batch_id"]:
                refresh_batch_amounts(db, fresh["batch_id"])
            db.commit()
            flash("发票已保存", "success")
            return redirect(url_for("invoices.index"))
        except ValueError as exc:
            safe_rollback(db)
            errors = [str(exc)]
        except Exception:
            safe_rollback(db)
            _logger().exception("edit invoice failed")
            errors = ["保存失败，请重试"]
    official = _official_rate(db, form.get("exchange_month") or current_month())
    selected = None
    if str(form.get("contract_id") or "").isdigit():
        selected = db.execute("SELECT * FROM contracts WHERE id=?", (int(form["contract_id"]),)).fetchone()
    return render_template(
        "invoice_form.html",
        form=form,
        errors=errors,
        editing=True,
        record=row,
        years=year_options(),
        batches=recent_batches(db),
        official=official,
        selected=selected,
    )


@bp.route("/<int:iid>/manual", methods=["GET", "POST"])
@login_required
def manual(iid):
    user = current_user()
    if not can_manual(user):
        abort(403)
    db = get_db()
    row = _alive(db, iid)
    if row["is_batch"]:
        abort(400, description="批次发票编号按批次规则管理。如需调整，请删除后重新登记。")
    history = db.execute(
        """SELECT * FROM number_edit_logs
           WHERE target_type='invoice' AND target_id=? ORDER BY id DESC""",
        (iid,),
    ).fetchall()
    errors = []
    if request.method == "POST":
        new_no = (request.form.get("new_no") or "").strip()
        reason = (request.form.get("reason") or "").strip()
        try:
            begin_immediate(db)
            fresh = _alive(db, iid)
            _apply_manual(db, fresh, new_no, reason, user)
            db.commit()
            flash(f"发票号已修改为 {new_no}", "success")
            return redirect(url_for("invoices.index"))
        except ValueError as exc:
            safe_rollback(db)
            errors = [str(exc)]
        except Exception:
            safe_rollback(db)
            _logger().exception("manual invoice failed")
            errors = ["保存失败，请重试"]
    return render_template(
        "manual_form.html",
        title="手动编辑发票号",
        old_no=row["invoice_no"],
        errors=errors,
        history=history,
        back_url=url_for("invoices.edit", iid=iid),
    )


@bp.route("/<int:iid>/delete", methods=["POST"])
@login_required
def delete(iid):
    user = current_user()
    db = get_db()
    try:
        begin_immediate(db)
        row = _alive(db, iid)
        if not can_mutate(user, row):
            safe_rollback(db)
            flash("只能删除自己登记的发票", "error")
            return redirect(url_for("invoices.index"))
        if row["is_batch_master"]:
            batch = db.execute(
                "SELECT * FROM batches WHERE id=? AND deleted_at IS NULL",
                (row["batch_id"],),
            ).fetchone()
            if batch and not _can_delete_batch(db, batch, user):
                safe_rollback(db)
                flash("批次中包含其他用户登记的发票，请联系管理员删除", "error")
                return redirect(url_for("invoices.index"))
            if batch:
                delete_batch_tree(db, batch, user)
            else:
                _delete_plain(db, row, user)
        else:
            _delete_plain(db, row, user)
        db.commit()
        flash(f"已删除发票 {row['invoice_no']}，编号已进入空闲池", "success")
    except Exception:
        safe_rollback(db)
        _logger().exception("delete invoice failed")
        flash("删除失败，请重试", "error")
    return redirect(url_for("invoices.index"))


@bp.route("/batch-delete", methods=["POST"])
@login_required
def batch_delete():
    user = current_user()
    ids = [int(item) for item in request.form.getlist("ids") if str(item).isdigit()]
    if not ids:
        flash("请先选择发票", "error")
        return redirect(url_for("invoices.index"))
    db = get_db()
    done = 0
    skipped = 0
    try:
        begin_immediate(db)
        seen_batches = set()
        for iid in ids[:200]:
            row = db.execute(
                "SELECT * FROM invoices WHERE id=? AND deleted_at IS NULL",
                (iid,),
            ).fetchone()
            if not row or not can_mutate(user, row):
                skipped += 1
                continue
            if row["is_batch_master"] and row["batch_id"]:
                if row["batch_id"] in seen_batches:
                    continue
                batch = db.execute(
                    "SELECT * FROM batches WHERE id=? AND deleted_at IS NULL",
                    (row["batch_id"],),
                ).fetchone()
                if not batch or not _can_delete_batch(db, batch, user):
                    skipped += 1
                    continue
                delete_batch_tree(db, batch, user)
                seen_batches.add(row["batch_id"])
                done += 1
            else:
                _delete_plain(db, row, user)
                done += 1
        db.commit()
    except Exception:
        safe_rollback(db)
        _logger().exception("batch delete invoice failed")
        flash("删除失败，请重试", "error")
        return redirect(url_for("invoices.index"))
    message = f"已删除 {done} 条发票，编号已进入空闲池"
    if skipped:
        message += f"，跳过 {skipped} 条（无权限、已删除或批次内含他人发票）"
    flash(message, "success" if done else "error")
    return redirect(url_for("invoices.index"))


@bp.route("/export")
@login_required
def export_xlsx():
    where, params = _filters()
    db = get_db()
    refresh_open_batch_amounts(db)
    rows = db.execute(
        f"""SELECT i.*, c.contract_no
            FROM invoices i LEFT JOIN contracts c ON c.id=i.contract_id
            WHERE {where} ORDER BY {sort_sql(INVOICE_SORT, INVOICE_RECENT, 'i.id DESC')} LIMIT 50000""",
        params,
    ).fetchall()
    wb = Workbook()
    ws = wb.active
    ws.title = "发票登记"
    headers = [
        "序号", "发票号", "关联合同", "所含内容", "提单日期", "价格条款", "结算币种",
        "美元金额", "人民币金额", "汇率", "汇率月份", "PO", "操作人", "运输方式",
        "发邮件时间", "备注", "提单号", "是否批次", "批次前缀", "小批号",
    ]
    ws.append(headers)
    for index, row in enumerate(rows, start=1):
        ws.append(
            [
                index,
                excel_text(row["invoice_no"]),
                excel_text(row["contract_no"] or ""),
                excel_text(row["content"]),
                row["bl_date"] or "",
                row["price_term"],
                row["currency"],
                float(row["amount_usd"]),
                float(row["amount_cny"]),
                float(row["exchange_rate"]),
                row["exchange_month"],
                excel_text(row["po_no"] or ""),
                excel_text(row["operator_name"]),
                row["transport_type"],
                row["email_sent_date"] or "",
                excel_text(row["remark"] or ""),
                excel_text(row["bl_no"] or ""),
                "是" if row["is_batch"] else "否",
                excel_text(row["batch_prefix"] or ""),
                excel_text(row["batch_sub_no"] or ""),
            ]
        )
    _style_sheet(ws, money_cols={8, 9})
    for cell in ws.iter_rows(min_row=2, min_col=10, max_col=10):
        cell[0].number_format = "0.000000"
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    from datetime import date

    filename = f"发票登记_{date.today().strftime('%Y%m%d')}.xlsx"
    return send_file(
        bio,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/import", methods=["GET", "POST"])
@login_required
def import_xlsx():
    user = current_user()
    if not can_write(user):
        abort(403)
    result = None
    if request.method == "POST":
        result, message, category = handle_import_request(
            "invoice", get_db(), user, current_app.testing
        )
        flash(message, category)
    return render_template("import.html", result=result, **import_page("invoice"))


@bp.route("/import-template")
@login_required
def import_template():
    user = current_user()
    if not can_write(user):
        abort(403)
    payload, filename = template_bytes("invoice")
    return send_file(
        BytesIO(payload),
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/api/preview")
@login_required
def preview():
    rule = request.args.get("number_rule") or ""
    year = request.args.get("year") or ""
    if rule not in RULE_POOL or not str(year).isdigit():
        return jsonify({"ok": False, "message": "请选择编号规则和年份"})
    year = int(year)
    try:
        got = preview_number(get_db(), RULE_POOL[rule], year)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)})
    return jsonify({"ok": True, "number": got["number"], "reused": got["reused"]})


@bp.route("/api/preview-sub")
@login_required
def preview_sub_api():
    batch_id = request.args.get("batch_id") or ""
    if not str(batch_id).isdigit():
        return jsonify({"ok": False, "message": "请选择批次"})
    db = get_db()
    try:
        batch = _joinable_batch(db, int(batch_id))
        got = preview_sub(db, batch["id"], batch["prefix"])
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)})
    return jsonify({"ok": True, "number": got["number"], "reused": got["reused"], "sub_no": got["sub_no"]})


@bp.route("/api/rate")
@login_required
def rate_api():
    month = (request.args.get("month") or "").strip()
    try:
        month = parse_month(month, "汇率月份", required=True)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)})
    row = _official_rate(get_db(), month)
    if not row:
        return jsonify({"ok": True, "found": False, "month": month})
    return jsonify({"ok": True, "found": True, "month": month, "rate": row["rate"]})


@bp.route("/api/contracts")
@login_required
def search_contracts():
    args = request.args
    where = ["deleted_at IS NULL"]
    params = []
    keyword = (args.get("keyword") or "").strip()
    if keyword:
        token = like(keyword)
        where.append(
            "(contract_no LIKE ? ESCAPE '\\' OR product_name LIKE ? ESCAPE '\\' OR party_b LIKE ? ESCAPE '\\' OR party_a LIKE ? ESCAPE '\\')"
        )
        params.extend([token, token, token, token])
    for key, column in (
        ("contract_no", "contract_no"),
        ("product_name", "product_name"),
        ("party_b", "party_b"),
        ("party_a", "party_a"),
    ):
        value = (args.get(key) or "").strip()
        if value:
            where.append(f"{column} LIKE ? ESCAPE '\\'")
            params.append(like(value))
    if args.get("business_type") in ("锰矿", "铝矿"):
        where.append("business_type=?")
        params.append(args.get("business_type"))
    if (args.get("sign_from") or "").strip():
        where.append("sign_date>=?")
        params.append(args.get("sign_from").strip())
    if (args.get("sign_to") or "").strip():
        where.append("sign_date<=?")
        params.append(args.get("sign_to").strip())
    sql_where = " AND ".join(where)
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) AS n FROM contracts WHERE {sql_where}", params).fetchone()["n"]
    rows = db.execute(
        f"""SELECT id, contract_no, business_type, product_name, party_b, party_a, sign_date, amount_cny
            FROM contracts WHERE {sql_where} ORDER BY {CONTRACT_RECENT} LIMIT 20""",
        params,
    ).fetchall()
    items = [
        {
            "id": row["id"],
            "contract_no": row["contract_no"],
            "business_type": row["business_type"],
            "product_name": row["product_name"],
            "party_b": row["party_b"],
            "party_a": row["party_a"],
            "sign_date": row["sign_date"],
            "amount_cny": row["amount_cny"],
        }
        for row in rows
    ]
    return jsonify({"ok": True, "total": total, "items": items})


def _insert_invoice(db, data, user):
    ts = now_str()
    reused = False
    number = None
    pool = None
    seq = None
    batch_id = None
    prefix = None
    sub_no = None
    sub_seq = None
    is_batch = 0
    is_master = 0
    mode = data["mode"]
    if mode == "join_batch":
        batch = data["batch"]
        got = allocate_sub(db, batch["id"], batch["prefix"])
        number = got["number"]
        sub_no = got["sub_no"]
        sub_seq = got["seq"]
        reused = got["reused"]
        batch_id = batch["id"]
        prefix = batch["prefix"]
        is_batch = 1
    else:
        pool_key = RULE_POOL[data["number_rule"]]
        got = allocate_number(db, pool_key, data["number_year"])
        number = got["number"]
        pool = got["pool"]
        seq = got["seq"]
        reused = got["reused"]
        if mode == "new_batch":
            is_batch = 1
            is_master = 1
            prefix = number
            cur = db.execute(
                """INSERT INTO batches
                   (prefix, number_rule, number_year, transport_type, business_type,
                    num_pool, num_seq, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    prefix,
                    data["number_rule"],
                    data["number_year"],
                    data["transport_type"],
                    data["business_type"],
                    pool,
                    seq,
                    user["id"],
                    ts,
                ),
            )
            batch_id = cur.lastrowid
    cur = db.execute(
        """INSERT INTO invoices
           (invoice_no, contract_id, business_type, number_rule, number_year, num_pool, num_seq,
            content, bl_date, price_term, currency, amount_usd, amount_cny, exchange_rate,
            exchange_month, rate_adjusted, po_no, operator_id, operator_name, transport_type,
            email_sent_date, remark, bl_no, is_batch, is_batch_master, batch_id, batch_prefix,
            batch_sub_no, sub_seq, manual_edited, created_by, updated_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
        (
            number,
            data["contract_id"],
            data["business_type"],
            data["number_rule"],
            data["number_year"],
            pool,
            seq,
            data["content"],
            data["bl_date"] or None,
            data["price_term"],
            data["currency"],
            data["amount_usd"],
            data["amount_cny"],
            data["exchange_rate"],
            data["exchange_month"],
            data["rate_adjusted"],
            data["po_no"] or None,
            user["id"],
            user["display_name"],
            data["transport_type"],
            data["email_sent_date"] or None,
            data["remark"] or None,
            data["bl_no"] or None,
            is_batch,
            is_master,
            batch_id,
            prefix,
            sub_no,
            sub_seq,
            user["id"],
            user["id"],
            ts,
            ts,
        ),
    )
    rule_label = data["number_rule"]
    log_op(
        db,
        user,
        "invoice_create",
        f"新增发票 {number}" + ("，已复用空闲编号" if reused else ""),
        "invoice",
        cur.lastrowid,
        {
            "业务类型": data["business_type"],
            "编号规则": rule_label,
            "编号年份": data["number_year"],
            "生成编号": number,
            "操作人": user["display_name"],
            "生成时间": ts,
            "复用空闲编号": reused,
            "批次": bool(is_batch),
            "汇率已手工调整": bool(data["rate_adjusted"]),
            "汇率": data["exchange_rate"],
            "汇率月份": data["exchange_month"],
        },
    )
    if batch_id:
        refresh_batch_amounts(db, batch_id)
    return {"invoice_no": number, "reused": reused, "id": cur.lastrowid}


def _apply_manual(db, row, new_no, reason, user):
    if row["is_batch"]:
        raise ValueError("批次发票编号不支持手动编辑")
    if not new_no or len(new_no) > 64 or any(ch.isspace() for ch in new_no):
        raise ValueError("新编号不能为空、不能含空白，且不超过 64 个字符")
    if len(reason) < 2 or len(reason) > 200:
        raise ValueError("请填写修改原因（2 到 200 个字）")
    if new_no == row["invoice_no"]:
        raise ValueError("新编号与原编号相同")
    if number_exists(db, new_no, except_invoice_id=row["id"]):
        raise ValueError("编号已存在，请更换")
    pool = row["num_pool"] or RULE_POOL[row["number_rule"]]
    parsed = parse_pool_number(pool, new_no)
    if parsed is None and matches_any_pattern(new_no):
        raise ValueError("编号格式与当前编号规则不一致")
    old_pool, old_seq = row["num_pool"], row["num_seq"]
    new_year = row["number_year"]
    new_pool = None
    new_seq = None
    if parsed:
        new_year, new_seq = parsed
        new_pool = pool
        if slot_blocked(db, pool, new_seq, self_invoice_id=row["id"]):
            raise ValueError("该顺序号已被其他记录占用")
    ts = now_str()
    db.execute(
        """UPDATE invoices
           SET invoice_no=?, number_year=?, num_pool=?, num_seq=?, manual_edited=1,
               updated_by=?, updated_at=?
           WHERE id=?""",
        (new_no, new_year, new_pool, new_seq, user["id"], ts, row["id"]),
    )
    if old_pool and old_seq and not (old_pool == new_pool and old_seq == new_seq):
        if not slot_blocked(db, old_pool, old_seq, self_invoice_id=row["id"]):
            release_number(db, old_pool, old_seq)
    if parsed:
        occupy_slot(db, new_pool, new_seq, new_year, new_no)
    db.execute(
        """INSERT INTO number_edit_logs
           (target_type, target_id, old_no, new_no, reason, operator_id, operator_name, created_at)
           VALUES ('invoice', ?, ?, ?, ?, ?, ?, ?)""",
        (row["id"], row["invoice_no"], new_no, reason, user["id"], user["display_name"], ts),
    )
    log_op(
        db,
        user,
        "number_manual_edit",
        f"手动编辑发票号 {row['invoice_no']} -> {new_no}",
        "invoice",
        row["id"],
        {"原编号": row["invoice_no"], "新编号": new_no, "原因": reason, "操作人": user["display_name"], "操作时间": ts},
    )


def _alive(db, iid):
    row = db.execute(
        "SELECT * FROM invoices WHERE id=? AND deleted_at IS NULL",
        (iid,),
    ).fetchone()
    if not row:
        abort(404)
    return row


def _can_delete_batch(db, batch, user):
    if user["role"] == "admin":
        return True
    if batch["created_by"] != user["id"]:
        return False
    others = db.execute(
        """SELECT id FROM invoices
           WHERE batch_id=? AND deleted_at IS NULL AND created_by!=?""",
        (batch["id"], user["id"]),
    ).fetchone()
    return others is None


def _delete_plain(db, row, user):
    if row["is_batch_master"]:
        raise ValueError("批次前缀请按批次删除")
    if row["sub_seq"] and row["batch_id"]:
        release_sub(db, row["batch_id"], row["sub_seq"])
    elif row["num_pool"] and row["num_seq"]:
        if not slot_blocked(db, row["num_pool"], row["num_seq"], self_invoice_id=row["id"]):
            release_number(db, row["num_pool"], row["num_seq"])
    _mark_deleted(db, row, user, f"删除发票 {row['invoice_no']}，编号回收")
    if row["batch_id"]:
        refresh_batch_amounts(db, row["batch_id"])


def delete_batch_tree(db, batch, user):
    rows = db.execute(
        "SELECT * FROM invoices WHERE batch_id=? AND deleted_at IS NULL",
        (batch["id"],),
    ).fetchall()
    for row in rows:
        if row["is_batch_master"]:
            continue
        if row["sub_seq"]:
            release_sub(db, batch["id"], row["sub_seq"])
        _mark_deleted(db, row, user, f"随批次 {batch['prefix']} 删除发票 {row['invoice_no']}")
    for row in rows:
        if not row["is_batch_master"]:
            continue
        if row["num_pool"] and row["num_seq"] and not slot_blocked(
            db, row["num_pool"], row["num_seq"], self_invoice_id=row["id"]
        ):
            release_number(db, row["num_pool"], row["num_seq"])
        _mark_deleted(db, row, user, f"删除批次前缀发票 {row['invoice_no']}")
    if not any(row["is_batch_master"] for row in rows):
        if batch["num_pool"] and batch["num_seq"] and not slot_blocked(db, batch["num_pool"], batch["num_seq"]):
            release_number(db, batch["num_pool"], batch["num_seq"])
    ts = now_str()
    db.execute(
        "UPDATE batches SET deleted_at=?, deleted_by=? WHERE id=?",
        (ts, user["id"], batch["id"]),
    )
    log_op(
        db,
        user,
        "batch_delete",
        f"删除批次 {batch['prefix']}，前缀与小批号回收",
        "batch",
        batch["id"],
        {"批次前缀": batch["prefix"], "编号规则": batch["number_rule"]},
    )


def _mark_deleted(db, row, user, summary):
    ts = now_str()
    db.execute(
        """UPDATE invoices SET deleted_at=?, deleted_by=?, updated_at=?
           WHERE id=? AND deleted_at IS NULL""",
        (ts, user["id"], ts, row["id"]),
    )
    log_op(
        db,
        user,
        "invoice_delete",
        summary,
        "invoice",
        row["id"],
        {"发票号": row["invoice_no"], "编号池": row["num_pool"], "顺序号": row["num_seq"], "小批号": row["sub_seq"]},
    )


def sub_summary(db, batch_id):
    rows = db.execute(
        "SELECT seq, status FROM batch_slots WHERE batch_id=? ORDER BY seq",
        (batch_id,),
    ).fetchall()

    def fmt(number):
        return f"{number:03d}" if number < 1000 else str(number)

    used = [row["seq"] for row in rows if row["status"] == "used"]
    free = [row["seq"] for row in rows if row["status"] == "free"]
    next_seq = (max(row["seq"] for row in rows) + 1) if rows else 1
    usd, cny, _has_children = batch_amount_totals(db, batch_id)
    refresh_batch_amounts(db, batch_id)
    return {
        "used": "、".join(fmt(item) for item in used) or "无",
        "free": "、".join(fmt(item) for item in free) or f"无空闲（下一号 {fmt(next_seq)}）",
        "usd": usd,
        "cny": cny,
    }


def _logger():
    import logging

    return logging.getLogger("invoiceapp")
