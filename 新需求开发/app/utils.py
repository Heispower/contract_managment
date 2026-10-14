import calendar
import socket
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlencode

from flask import request


def lan_ipv4():
    """本机非回环 IPv4，供同一局域网的其他电脑访问。"""
    found = []
    seen = set()

    def add(ip):
        if not ip or ip.startswith("127.") or ip in seen:
            return
        seen.add(ip)
        found.append(ip)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.168.0.1", 9))
            add(sock.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass
    return found


def listen_port():
    port_file = Path(__file__).resolve().parents[1] / "data" / "port.txt"
    if port_file.exists():
        text = port_file.read_text(encoding="utf-8").strip()
        if text.isdigit():
            return int(text)
    return 6688


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return date.today().strftime("%Y-%m-%d")


def current_month():
    return date.today().strftime("%Y-%m")


def add_months(dt, months):
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def default_number_year(today=None):
    """1 月默认上一年年尾所属年度，其余月份默认当年。"""
    today = today or date.today()
    if today.month == 1:
        return today.year - 1
    return today.year


def year_options(today=None):
    today = today or date.today()
    start = min(2020, today.year - 1)
    end = today.year + 1
    return list(range(start, end + 1))


def clean_text(value, limit, name, required=False):
    text = "" if value is None else str(value).strip()
    if not text:
        if required:
            raise ValueError(f"{name}不能为空")
        return ""
    if len(text) > limit:
        raise ValueError(f"{name}不能超过 {limit} 个字符")
    return text


def parse_date(value, name, required=False):
    text = "" if value is None else str(value).strip().replace("/", "-")
    if not text:
        if required:
            raise ValueError(f"{name}不能为空")
        return ""
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{name}必须为 YYYY-MM-DD")
    return text


def parse_month(value, name, required=False):
    text = "" if value is None else str(value).strip()
    if not text:
        if required:
            raise ValueError(f"{name}不能为空")
        return ""
    try:
        datetime.strptime(text, "%Y-%m")
    except ValueError:
        raise ValueError(f"{name}必须为 YYYY-MM")
    return text


def parse_decimal(value, places, name, required=False):
    text = "" if value is None else str(value).strip().replace(",", "")
    if not text:
        if required:
            raise ValueError(f"{name}不能为空")
        return ""
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"{name}必须是数字")
    if number < 0:
        raise ValueError(f"{name}不能为负数")
    quant = Decimal("1").scaleb(-places)
    number = number.quantize(quant, rounding=ROUND_HALF_UP)
    return format(number, "f")


def money_mul(amount, rate):
    value = (Decimal(amount) * Decimal(rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(value, "f")


def money_div(amount, rate):
    if Decimal(rate) == 0:
        raise ValueError("汇率不能为 0")
    value = (Decimal(amount) / Decimal(rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(value, "f")


def _money_text(value):
    number = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(number, "f")


def batch_amount_totals(db, batch_id):
    """批次前缀金额取小批发票合计；还没有小批时，沿用前缀自己的金额。"""
    rows = db.execute(
        """SELECT is_batch_master, amount_usd, amount_cny
           FROM invoices WHERE batch_id=? AND deleted_at IS NULL""",
        (batch_id,),
    ).fetchall()
    children = [row for row in rows if not row["is_batch_master"]]
    source = children or [row for row in rows if row["is_batch_master"]]
    usd = Decimal("0")
    cny = Decimal("0")
    for row in source:
        usd += Decimal(row["amount_usd"] or "0")
        cny += Decimal(row["amount_cny"] or "0")
    return _money_text(usd), _money_text(cny), bool(children)


def refresh_batch_amounts(db, batch_id):
    """有小批发票后，把美元、人民币合计写回批次前缀。"""
    if not batch_id:
        return
    usd, cny, has_children = batch_amount_totals(db, batch_id)
    if not has_children:
        return
    master = db.execute(
        """SELECT id, amount_usd, amount_cny FROM invoices
           WHERE batch_id=? AND deleted_at IS NULL AND is_batch_master=1""",
        (batch_id,),
    ).fetchone()
    if not master or (master["amount_usd"] == usd and master["amount_cny"] == cny):
        return
    db.execute(
        "UPDATE invoices SET amount_usd=?, amount_cny=?, updated_at=? WHERE id=?",
        (usd, cny, now_str(), master["id"]),
    )


def refresh_open_batch_amounts(db):
    """按已经存在的小批发票，回写每个批次前缀的美元、人民币合计。"""
    rows = db.execute(
        """SELECT DISTINCT batch_id FROM invoices
           WHERE deleted_at IS NULL AND is_batch_master=0 AND batch_id IS NOT NULL"""
    ).fetchall()
    for row in rows:
        refresh_batch_amounts(db, row["batch_id"])


def like(value):
    text = str(value).strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{text}%"


def page_args(default_size=50):
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    try:
        size = int(request.args.get("page_size", default_size))
    except (TypeError, ValueError):
        size = default_size
    if size not in (20, 50, 100):
        size = default_size
    return max(page, 1), size


def page_window(page, pages, span=2):
    items = []
    last = 0
    for i in range(1, pages + 1):
        if i == 1 or i == pages or abs(i - page) <= span:
            if last and i - last > 1:
                items.append(None)
            items.append(i)
            last = i
    return items


def build_pager(total, page, page_size):
    pages = max(1, (total + page_size - 1) // page_size) if total else 1
    page = min(max(page, 1), pages)
    start = 0 if total == 0 else (page - 1) * page_size + 1
    end = min(page * page_size, total)
    return {
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": page_size,
        "start": start,
        "end": end,
        "offset": (page - 1) * page_size,
        "window": page_window(page, pages),
    }


def sort_sql(allowed, default, tie="id DESC"):
    """按白名单字段排序。sort、order 来自地址栏，非法值退回默认顺序。"""
    key = (request.args.get("sort") or "").strip()
    order = (request.args.get("order") or "").strip().lower()
    expr = allowed.get(key)
    if not expr or order not in ("asc", "desc"):
        return default
    return f"{expr} {order.upper()}, {tie}"


def keep_qs(**kwargs):
    params = request.args.to_dict(flat=True)
    for key, value in kwargs.items():
        if value is None or value == "":
            params.pop(key, None)
        else:
            params[key] = str(value)
    return urlencode(params)


def form_dict():
    return {key: request.form.get(key, "") for key in request.form.keys()}


def excel_text(value):
    if value is None:
        return ""
    text = str(value)
    if text[:1] in ("=", "+", "-", "@"):
        return "'" + text
    return text


ROLE_LABELS = {
    "admin": "系统管理员",
    "user": "普通业务用户",
    "viewer": "查看用户",
}

STATUS_LABELS = {
    "active": "启用",
    "disabled": "禁用",
}

DEFAULT_PARTY_A = "重庆市博赛国际矿业投资有限公司"
