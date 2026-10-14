"""第 6 章金额公式。全程 Decimal，禁止用浮点累加。"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .errors import BizError

CENT = Decimal("0.01")
MICRO = Decimal("0.000001")
ZERO = Decimal("0")


def D(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise BizError(f"数值不正确：{value}")


def round2(value) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def round6(value) -> Decimal:
    return D(value).quantize(MICRO, rounding=ROUND_HALF_UP)


def line_total(qty, price) -> Decimal:
    """行价税合计，行上唯一主值。"""
    return round2(D(qty) * D(price))


def line_ex_tax(total, tax_rate) -> Decimal:
    rate = D(tax_rate) / Decimal("100")
    return round2(D(total) / (Decimal("1") + rate))


def line_tax(total, ex_tax) -> Decimal:
    return round2(D(total) - D(ex_tax))


def split_line(qty, price, tax_rate) -> dict:
    total = line_total(qty, price)
    ex_tax = line_ex_tax(total, tax_rate)
    tax = line_tax(total, ex_tax)
    return {"total": total, "ex_tax": ex_tax, "tax": tax, "price": D(price)}


def price_ex_tax_display(ex_tax, qty) -> Decimal:
    qty = D(qty)
    if qty == 0:
        return ZERO
    return round6(D(ex_tax) / qty)


def price_matching_total(total, qty) -> Decimal:
    """反算含税单价，优先 2 位，必要时用 6 位，使 round(数量×单价, 2) 等于价税合计。"""
    total = round2(total)
    qty = D(qty)
    if qty == 0:
        return ZERO
    p2 = round2(total / qty)
    if line_total(qty, p2) == total:
        return p2
    p6 = round6(total / qty)
    if line_total(qty, p6) == total:
        return p6
    step = MICRO
    for i in range(1, 30):
        for sign in (1, -1):
            cand = p6 + step * i * sign
            if line_total(qty, cand) == total:
                return cand
    return p6


def back_calc_from_ex_tax(qty, ex_tax, tax) -> dict:
    """直接改不含税金额或税额：价税合计 = 两者之和，再反算含税单价。"""
    qty = D(qty)
    if qty <= 0:
        raise ValueError("数量必须大于 0")
    ex_tax = round2(ex_tax)
    tax = round2(tax)
    total = round2(ex_tax + tax)
    price = price_matching_total(total, qty)
    checked = line_total(qty, price)
    if checked != total:
        total = checked
        tax = line_tax(total, ex_tax)
    else:
        tax = line_tax(total, ex_tax)
    return {"total": total, "ex_tax": ex_tax, "tax": tax, "price": price}


def max0(value) -> Decimal:
    value = D(value)
    return value if value > 0 else ZERO


def allocate(total, weights: list) -> list[Decimal]:
    """按权重分摊，尾差进最后一行。权重合计为 0 时按行数均分。"""
    total = round2(total)
    n = len(weights)
    if n == 0:
        return []
    weights = [D(w) for w in weights]
    base = sum(weights, ZERO)
    amounts: list[Decimal] = []
    if base == 0:
        acc = ZERO
        for _ in range(n - 1):
            part = round2(total / Decimal(n))
            amounts.append(part)
            acc += part
        amounts.append(round2(total - acc))
        return amounts
    acc = ZERO
    for i, w in enumerate(weights):
        if i == n - 1:
            amounts.append(round2(total - acc))
        else:
            part = round2(total * w / base)
            amounts.append(part)
            acc += part
    return amounts


def money_str(value) -> str:
    return format(round2(value), "f")


def qty_str(value) -> str:
    text = format(D(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
