"""合同编号与发票编号。

五个编号池各自回收：删除后优先复用大于顺序号下限的最小空号。
1 月默认编入上一年，其余月份默认当年。对不上当前规则的历史编号原样保存，不占顺序号。
"""
import re
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from ..errors import BizError
from ..models import (
    Company,
    Contract,
    CustomsInvoice,
    CustomsInvoiceItem,
    ExchangeRate,
    NumberBatch,
    NumberBatchSlot,
    NumberContract,
    NumberEditLog,
    NumberInvoice,
    NumberSetting,
    NumberSlot,
    SysUser,
    now,
)
from ..money import D, money_str, round2
from .util import bump, get_row, name_of, op_log, parse_date, q, soft_delete, stamp_new, user_names

DEFAULT_PARTY_A = "重庆市博赛国际矿业投资有限公司"

CONTRACT_POOL = {"锰矿": "contract_mn", "铝矿": "contract_al"}
RULE_POOL = {"铝矿海运": "invoice_al_sea", "铝矿空运": "invoice_al_air", "锰矿": "invoice_mn"}
POOL_LABELS = {
    "contract_mn": "锰矿合同",
    "contract_al": "铝矿合同",
    "invoice_al_sea": "铝矿海运",
    "invoice_al_air": "铝矿空运",
    "invoice_mn": "锰矿发票",
}
POOL_BUSINESS = {
    "contract_mn": "锰矿",
    "contract_al": "铝矿",
    "invoice_mn": "锰矿",
    "invoice_al_sea": "铝矿",
    "invoice_al_air": "铝矿",
}
POOL_RULE = {"invoice_al_sea": "铝矿海运", "invoice_al_air": "铝矿空运", "invoice_mn": "锰矿"}
POOL_TRANSPORT = {"invoice_al_sea": "海运", "invoice_al_air": "空运", "invoice_mn": "海运"}
PATTERNS = {
    "contract_mn": re.compile(r"^BMI-GMI-(\d{4})(\d{3,})$"),
    "contract_al": re.compile(r"^BMGG-MAZ-(\d{2})(\d{3,})$"),
    "invoice_al_sea": re.compile(r"^BMI-BMGGMAZ-(\d{2})(\d{3,})S$"),
    "invoice_al_air": re.compile(r"^BMI-BMGGMAZ-(\d{2})(\d{3,})A$"),
    "invoice_mn": re.compile(r"^(\d{4})(\d{4,})$"),
}
TWO_DIGIT_YEAR = {"contract_al", "invoice_al_sea", "invoice_al_air"}
CONTRACT_POOLS = set(CONTRACT_POOL.values())
INVOICE_POOLS = set(RULE_POOL.values())


def default_number_year(today=None):
    today = today or date.today()
    if today.month == 1:
        return today.year - 1
    return today.year


def year_options(today=None):
    today = today or date.today()
    return list(range(2020, today.year + 2))


def normalize_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        raise BizError("编号年份不正确")
    if year < 100:
        year += 2000
    if year < 2000 or year > 2099:
        raise BizError("编号年份不正确")
    return year


def parse_year(value):
    if value in (None, ""):
        return default_number_year()
    return normalize_year(value)


def format_number(pool, year, seq):
    year = int(year)
    seq = int(seq)
    if pool == "contract_mn":
        return f"BMI-GMI-{year}{seq:03d}"
    if pool == "contract_al":
        return f"BMGG-MAZ-{year % 100:02d}{seq:03d}"
    if pool == "invoice_al_sea":
        return f"BMI-BMGGMAZ-{year % 100:02d}{seq:03d}S"
    if pool == "invoice_al_air":
        return f"BMI-BMGGMAZ-{year % 100:02d}{seq:03d}A"
    if pool == "invoice_mn":
        return f"{year}{seq:04d}"
    raise BizError("未知编号规则")


def format_sub_no(seq):
    seq = int(seq)
    return f"-{seq:03d}" if seq < 1000 else f"-{seq}"


def parse_pool_number(pool, number):
    pattern = PATTERNS.get(pool)
    if not pattern or number is None:
        return None
    matched = pattern.match(str(number).strip())
    if not matched:
        return None
    seq = int(matched.group(2))
    if seq < 1:
        return None
    year = 2000 + int(matched.group(1)) if pool in TWO_DIGIT_YEAR else int(matched.group(1))
    if year < 2000 or year > 2099:
        return None
    return year, seq


def detect_pools(number):
    text = "" if number is None else str(number).strip()
    found = []
    for pool in PATTERNS:
        parsed = parse_pool_number(pool, text)
        if parsed:
            found.append((pool, parsed))
    return found


def matches_any_pattern(number):
    return bool(detect_pools(number))


def _clean(value, limit, name, required=False):
    text = "" if value is None else str(value).strip()
    if not text and required:
        raise BizError(f"{name}不能为空")
    if len(text) > limit:
        raise BizError(f"{name}不能超过 {limit} 个字符")
    return text


def party_a_name(db, company_id):
    company = db.get(Company, company_id)
    if company and company.name:
        return company.name
    return DEFAULT_PARTY_A


def number_exists(
    db,
    company_id,
    number,
    *,
    except_contract_id=None,
    except_invoice_id=None,
    except_batch_id=None,
    except_purchase_id=None,
    except_customs_id=None,
):
    text = "" if number is None else str(number).strip()
    if not text:
        return False
    row = q(db, NumberContract, company_id).filter(NumberContract.contract_no == text).first()
    if row and row.id != except_contract_id:
        return True
    row = q(db, NumberInvoice, company_id).filter(NumberInvoice.invoice_no == text).first()
    if row and row.id != except_invoice_id:
        return True
    row = q(db, NumberBatch, company_id).filter(NumberBatch.prefix == text).first()
    if row and row.id != except_batch_id:
        return True
    purchase = (
        db.query(Contract)
        .filter(Contract.company_id == company_id, Contract.contract_code == text, Contract.deleted_at.is_(None))
        .first()
    )
    if purchase and purchase.id != except_purchase_id:
        return True
    customs = (
        db.query(CustomsInvoice)
        .filter(CustomsInvoice.company_id == company_id, CustomsInvoice.invoice_no == text, CustomsInvoice.deleted_at.is_(None))
        .first()
    )
    if customs and customs.id != except_customs_id:
        return True
    return False


def pool_floor(db, company_id, pool):
    row = (
        db.query(NumberSetting)
        .filter(NumberSetting.company_id == company_id, NumberSetting.key == f"seq_floor:{pool}")
        .first()
    )
    if row is None or not str(row.value or "").strip().isdigit():
        return 0
    return int(row.value)


def parse_floor_value(pool, raw):
    text = "" if raw is None else str(raw).strip()
    if not text:
        raise BizError("请填写最新顺序号，或该规则的完整编号")
    parsed = parse_pool_number(pool, text)
    if parsed:
        return parsed[1]
    if matches_any_pattern(text):
        raise BizError("这个编号不属于当前规则")
    if not text.isdigit():
        raise BizError("请填写顺序号，或该规则的完整编号")
    seq = int(text)
    if seq < 1 or seq > 999999:
        raise BizError("顺序号需在 1 到 999999 之间")
    return seq


def set_pool_floor(db, company_id, pool, seq):
    if pool not in PATTERNS:
        raise BizError("未知编号规则")
    seq = int(seq)
    if seq < 0 or seq > 999999:
        raise BizError("顺序号需在 0 到 999999 之间")
    row = (
        db.query(NumberSetting)
        .filter(NumberSetting.company_id == company_id, NumberSetting.key == f"seq_floor:{pool}")
        .first()
    )
    if row is None:
        db.add(NumberSetting(company_id=company_id, key=f"seq_floor:{pool}", value=str(seq)))
    else:
        row.value = str(seq)
    db.flush()
    if seq > 0:
        (
            db.query(NumberSlot)
            .filter(NumberSlot.company_id == company_id, NumberSlot.pool_key == pool, NumberSlot.status == "free", NumberSlot.seq <= seq)
            .update({NumberSlot.status: "held", NumberSlot.year: None, NumberSlot.number: None, NumberSlot.updated_at: now()}, synchronize_session=False)
        )
    (
        db.query(NumberSlot)
        .filter(NumberSlot.company_id == company_id, NumberSlot.pool_key == pool, NumberSlot.status == "held", NumberSlot.seq > seq)
        .update({NumberSlot.status: "free", NumberSlot.updated_at: now()}, synchronize_session=False)
    )


def _slots(db, company_id, pool):
    return db.query(NumberSlot).filter(NumberSlot.company_id == company_id, NumberSlot.pool_key == pool).all()


def _free_and_max(db, company_id, pool):
    floor = pool_floor(db, company_id, pool)
    rows = _slots(db, company_id, pool)
    free = sorted(row.seq for row in rows if row.status == "free" and row.seq > floor)
    max_seq = max([row.seq for row in rows] + [floor, 0])
    return free, max_seq


def _candidate_seqs(free_seqs, max_seq, limit=40):
    seqs = []
    seen = set()
    for seq in list(free_seqs) + list(range(max_seq + 1, max_seq + 1 + limit)):
        if seq not in seen and seq >= 1:
            seen.add(seq)
            seqs.append(seq)
    return seqs


def preview_number(db, company_id, pool, year, **excepts):
    if pool not in PATTERNS:
        raise BizError("未知编号规则")
    year = normalize_year(year)
    free_seqs, max_seq = _free_and_max(db, company_id, pool)
    for seq in _candidate_seqs(free_seqs, max_seq):
        number = format_number(pool, year, seq)
        if number_exists(db, company_id, number, **excepts):
            continue
        return {"number": number, "seq": seq, "reused": seq in free_seqs, "pool": pool, "year": year}
    raise BizError("编号生成失败")


def _claim_slot(db, company_id, pool, seq, year, number, status="used"):
    slot = NumberSlot(
        company_id=company_id,
        pool_key=pool,
        seq=int(seq),
        status=status,
        year=int(year) if year not in (None, "") else None,
        number=number,
        updated_at=now(),
    )
    try:
        with db.begin_nested():
            db.add(slot)
            db.flush()
        return True
    except IntegrityError:
        return False


def allocate_number(db, company_id, pool, year, **excepts):
    if pool not in PATTERNS:
        raise BizError("未知编号规则")
    year = normalize_year(year)
    free_seqs, max_seq = _free_and_max(db, company_id, pool)
    free_set = set(free_seqs)
    for seq in _candidate_seqs(free_seqs, max_seq):
        number = format_number(pool, year, seq)
        if number_exists(db, company_id, number, **excepts):
            continue
        if seq in free_set:
            slot = (
                db.query(NumberSlot)
                .filter(
                    NumberSlot.company_id == company_id,
                    NumberSlot.pool_key == pool,
                    NumberSlot.seq == seq,
                    NumberSlot.status == "free",
                )
                .first()
            )
            if slot is None:
                continue
            slot.status = "used"
            slot.year = year
            slot.number = number
            slot.updated_at = now()
            db.flush()
            reused = True
        else:
            if not _claim_slot(db, company_id, pool, seq, year, number):
                continue
            reused = False
        return {"number": number, "seq": seq, "reused": reused, "pool": pool, "year": year}
    raise BizError("编号生成失败，请重试")


def release_number(db, company_id, pool, seq):
    if not pool or not seq:
        return
    status = "held" if int(seq) <= pool_floor(db, company_id, pool) else "free"
    slot = (
        db.query(NumberSlot)
        .filter(NumberSlot.company_id == company_id, NumberSlot.pool_key == pool, NumberSlot.seq == int(seq))
        .first()
    )
    if slot is None:
        return
    slot.status = status
    slot.year = None
    slot.number = None
    slot.updated_at = now()
    db.flush()


def slot_blocked(db, company_id, pool, seq, self_contract_id=None, self_invoice_id=None):
    contracts = q(db, NumberContract, company_id).filter(NumberContract.num_pool == pool, NumberContract.num_seq == int(seq)).all()
    if any(row.id != self_contract_id for row in contracts):
        return True
    invoices = q(db, NumberInvoice, company_id).filter(NumberInvoice.num_pool == pool, NumberInvoice.num_seq == int(seq)).all()
    if any(row.id != self_invoice_id for row in invoices):
        return True
    return False


def occupy_slot(db, company_id, pool, seq, year, number):
    seq = int(seq)
    year = int(year)
    have = {row.seq: row for row in _slots(db, company_id, pool)}
    floor = pool_floor(db, company_id, pool)
    for index in range(1, seq):
        if index in have:
            continue
        gap = "held" if index <= floor else "free"
        _claim_slot(db, company_id, pool, index, None, None, status=gap)
    have = {row.seq: row for row in _slots(db, company_id, pool)}
    current = have.get(seq)
    if current:
        if current.status == "used" and current.number and current.number != number:
            raise BizError("该顺序号已被占用")
        current.status = "used"
        current.year = year
        current.number = number
        current.updated_at = now()
        return
    if not _claim_slot(db, company_id, pool, seq, year, number):
        raise BizError("该顺序号已被占用")


def _sub_candidates(db, batch_id):
    rows = db.query(NumberBatchSlot).filter(NumberBatchSlot.batch_id == batch_id).all()
    free = sorted(row.seq for row in rows if row.status == "free")
    max_seq = max([row.seq for row in rows] + [0])
    return free, max_seq


def preview_sub(db, company_id, batch_id, prefix):
    free_seqs, max_seq = _sub_candidates(db, batch_id)
    for seq in _candidate_seqs(free_seqs, max_seq):
        sub_no = format_sub_no(seq)
        number = f"{prefix}{sub_no}"
        if number_exists(db, company_id, number, except_batch_id=batch_id):
            continue
        return {"number": number, "sub_no": sub_no, "seq": seq, "reused": seq in free_seqs}
    raise BizError("小批号生成失败")


def allocate_sub(db, company_id, batch_id, prefix):
    free_seqs, max_seq = _sub_candidates(db, batch_id)
    free_set = set(free_seqs)
    for seq in _candidate_seqs(free_seqs, max_seq):
        sub_no = format_sub_no(seq)
        number = f"{prefix}{sub_no}"
        if number_exists(db, company_id, number, except_batch_id=batch_id):
            continue
        if seq in free_set:
            slot = (
                db.query(NumberBatchSlot)
                .filter(NumberBatchSlot.batch_id == batch_id, NumberBatchSlot.seq == seq, NumberBatchSlot.status == "free")
                .first()
            )
            if slot is None:
                continue
            slot.status = "used"
            slot.number = number
            slot.updated_at = now()
            db.flush()
            reused = True
        else:
            try:
                with db.begin_nested():
                    db.add(NumberBatchSlot(company_id=company_id, batch_id=batch_id, seq=seq, status="used", number=number, updated_at=now()))
                    db.flush()
            except IntegrityError:
                continue
            reused = False
        return {"number": number, "sub_no": sub_no, "seq": seq, "reused": reused}
    raise BizError("小批号生成失败，请重试")


def release_sub(db, batch_id, seq):
    if not batch_id or not seq:
        return
    slot = db.query(NumberBatchSlot).filter(NumberBatchSlot.batch_id == batch_id, NumberBatchSlot.seq == int(seq)).first()
    if slot is None:
        return
    slot.status = "free"
    slot.number = None
    slot.updated_at = now()
    db.flush()


def _rule_of(business_type, transport_type, number_rule):
    if number_rule not in RULE_POOL:
        raise BizError("请选择编号规则")
    if transport_type not in ("海运", "空运"):
        raise BizError("请选择运输方式")
    if business_type not in ("锰矿", "铝矿"):
        raise BizError("请选择业务类型")
    if number_rule == "锰矿" and business_type != "锰矿":
        raise BizError("锰矿编号规则只能用于锰矿业务")
    if number_rule == "铝矿海运" and (business_type != "铝矿" or transport_type != "海运"):
        raise BizError("铝矿海运编号需要业务类型为铝矿且运输方式为海运")
    if number_rule == "铝矿空运" and (business_type != "铝矿" or transport_type != "空运"):
        raise BizError("铝矿空运编号需要业务类型为铝矿且运输方式为空运")


def official_rate(db, company_id, month):
    text = (month or "").strip()
    if len(text) != 7 or text[4] != "-":
        return None
    year, mon = int(text[:4]), int(text[5:7])
    row = (
        q(db, ExchangeRate, company_id)
        .filter(ExchangeRate.year == year, ExchangeRate.month == mon, ExchangeRate.currency == "USD")
        .first()
    )
    if row is None or not row.rate:
        return None
    return money_str(row.rate)


def _amounts(payload, official, allow_zero=False):
    month = _clean(payload.get("exchange_month"), 7, "汇率月份")
    if month and (len(month) != 7 or month[4] != "-"):
        raise BizError("汇率月份格式应为 YYYY-MM")
    if not month:
        today = date.today()
        month = f"{today.year:04d}-{today.month:02d}"
    posted = _clean(payload.get("exchange_rate"), 20, "汇率")
    usd = payload.get("amount_usd")
    cny = payload.get("amount_cny")
    usd = None if usd in (None, "") else round2(usd)
    cny = None if cny in (None, "") else round2(cny)
    zero_only = (usd is None or usd == 0) and (cny is None or cny == 0)
    if usd is None and cny is None and not allow_zero:
        raise BizError("请填写美元金额或人民币金额")
    if allow_zero and zero_only and not posted and not official:
        return {"exchange_month": month, "exchange_rate": Decimal("0"), "rate_adjusted": False, "amount_usd": Decimal("0"), "amount_cny": Decimal("0")}
    if not posted:
        if not official:
            if allow_zero and zero_only:
                return {"exchange_month": month, "exchange_rate": Decimal("0"), "rate_adjusted": False, "amount_usd": Decimal("0"), "amount_cny": Decimal("0")}
            raise BizError("当月尚未维护汇率，请先到基础资料录入，或在本页手工填写汇率")
        rate = D(official)
        adjusted = False
    else:
        rate = D(posted)
        if rate <= 0:
            raise BizError("汇率必须大于 0")
        adjusted = not official or D(official) != rate
    if usd is None and cny is None:
        usd, cny = Decimal("0"), Decimal("0")
    elif usd is not None and cny is None:
        cny = round2(usd * rate)
    elif cny is not None and usd is None:
        usd = round2(cny / rate) if rate else Decimal("0")
    return {"exchange_month": month, "exchange_rate": rate, "rate_adjusted": adjusted, "amount_usd": usd or Decimal("0"), "amount_cny": cny or Decimal("0")}


def contract_form_meta(db, contract):
    row = None
    if getattr(contract, "id", None):
        row = q(db, NumberContract, contract.company_id).filter(NumberContract.purchase_contract_id == contract.id).first()
        if row is None and contract.contract_code:
            row = q(db, NumberContract, contract.company_id).filter(NumberContract.contract_no == contract.contract_code).first()
    if row:
        return {"number_business": row.business_type or "锰矿", "number_year": row.number_year or default_number_year()}
    return {"number_business": "锰矿", "number_year": default_number_year()}


def take_purchase_number(db, company_id, payload):
    business = (payload.get("number_business") or payload.get("business_type") or "锰矿").strip()
    if business not in CONTRACT_POOL:
        raise BizError("采购合同自动编号只支持锰矿或铝矿")
    year = parse_year(payload.get("number_year"))
    got = allocate_number(db, company_id, CONTRACT_POOL[business], year)
    got["business_type"] = business
    return got


def take_invoice_number(db, company_id, payload):
    rule = (payload.get("number_rule") or "锰矿").strip()
    if rule not in RULE_POOL:
        raise BizError("报关发票自动编号只支持锰矿、铝矿海运或铝矿空运")
    year = parse_year(payload.get("number_year"))
    got = allocate_number(db, company_id, RULE_POOL[rule], year)
    got["number_rule"] = rule
    got["business_type"] = POOL_BUSINESS[got["pool"]]
    got["transport_type"] = POOL_TRANSPORT[got["pool"]]
    return got


def _fill_contract_fields(db, company_id, row, contract):
    row.product_name = (contract.subject_name or contract.name or "")[:200]
    row.party_b = (contract.party_name or "")[:200]
    row.party_a = party_a_name(db, company_id)[:200]
    row.amount_cny = contract.amount or Decimal("0")
    row.sign_date = contract.sign_date
    if not row.owner_id and contract.owner_id:
        row.owner_id = contract.owner_id
    if not row.business_type:
        row.business_type = "锰矿"
    if not row.number_year:
        row.number_year = default_number_year()


def _bind_pattern(db, company_id, row, number, pools, preferred=None, self_contract_id=None, self_invoice_id=None):
    """按编号占用顺序号。对不上规则的历史编号不占坑。"""
    number = (number or "").strip()
    hits = [(pool, parsed) for pool, parsed in detect_pools(number) if pool in pools]
    if preferred:
        parsed = parse_pool_number(preferred, number)
        if parsed is None:
            if hits:
                raise BizError("编号格式与当前编号规则不一致")
            if row.num_pool and row.num_seq:
                release_number(db, company_id, row.num_pool, row.num_seq)
            row.num_pool = None
            row.num_seq = None
            return None
        pool, year_seq = preferred, parsed
    elif len(hits) == 1:
        pool, year_seq = hits[0]
    elif not hits:
        if row.num_pool and row.num_seq:
            release_number(db, company_id, row.num_pool, row.num_seq)
        row.num_pool = None
        row.num_seq = None
        return None
    else:
        raise BizError("编号匹配了多条规则，请指定编号规则")
    year, seq = year_seq
    if slot_blocked(db, company_id, pool, seq, self_contract_id=self_contract_id, self_invoice_id=self_invoice_id):
        raise BizError("该顺序号已被其他记录占用")
    if row.num_pool and row.num_seq and (row.num_pool, row.num_seq) != (pool, seq):
        release_number(db, company_id, row.num_pool, row.num_seq)
    occupy_slot(db, company_id, pool, seq, year, number)
    row.num_pool = pool
    row.num_seq = seq
    row.number_year = year
    return pool


def sync_purchase_contract(db, user, company_id, contract, payload, allocated=None):
    if contract.direction != "purchase" or contract.nature != "main":
        return None
    linked = q(db, NumberContract, company_id).filter(NumberContract.purchase_contract_id == contract.id).first()
    same = q(db, NumberContract, company_id).filter(NumberContract.contract_no == contract.contract_code).first()
    if linked and same and linked.id != same.id:
        raise BizError("该合同编号已存在于合同编号表")
    row = linked or same
    if row and row.purchase_contract_id and row.purchase_contract_id != contract.id:
        raise BizError("该合同编号已关联其他采购合同")
    creating = row is None
    if creating:
        row = NumberContract(contract_no=contract.contract_code, purchase_contract_id=contract.id)
        stamp_new(row, user, company_id)
        db.add(row)
        db.flush()
    old_no = row.contract_no
    row.purchase_contract_id = contract.id
    row.contract_no = contract.contract_code
    if allocated:
        if row.num_pool and row.num_seq and (row.num_pool, row.num_seq) != (allocated["pool"], allocated["seq"]):
            release_number(db, company_id, row.num_pool, row.num_seq)
        row.num_pool = allocated["pool"]
        row.num_seq = allocated["seq"]
        row.number_year = allocated["year"]
        row.business_type = allocated["business_type"]
    else:
        preferred = CONTRACT_POOL.get((payload.get("number_business") or "").strip())
        if not creating and old_no == contract.contract_code and row.num_pool in CONTRACT_POOLS:
            preferred = row.num_pool
        pool = _bind_pattern(
            db, company_id, row, contract.contract_code, CONTRACT_POOLS,
            preferred=preferred, self_contract_id=row.id,
        )
        if pool:
            row.business_type = POOL_BUSINESS[pool]
        elif payload.get("number_business") in CONTRACT_POOL:
            row.business_type = payload.get("number_business")
    _fill_contract_fields(db, company_id, row, contract)
    if not creating:
        bump(row, user.employee_id)
    op_log(db, user, company_id, "回写合同编号", "number_contract", row.id, {"code": contract.contract_code})
    return row


def detach_purchase_contract(db, user, company_id, contract):
    row = q(db, NumberContract, company_id).filter(NumberContract.purchase_contract_id == contract.id).first()
    if row is None and contract.contract_code:
        found = q(db, NumberContract, company_id).filter(NumberContract.contract_no == contract.contract_code).first()
        if found and found.purchase_contract_id in (None, contract.id):
            row = found
    if row is None:
        return
    release_number(db, company_id, row.num_pool, row.num_seq)
    soft_delete(row, user.employee_id)
    db.flush()


def _invoice_content(db, company_id, invoice):
    items = (
        q(db, CustomsInvoiceItem, company_id)
        .filter(CustomsInvoiceItem.invoice_id == invoice.id)
        .order_by(CustomsInvoiceItem.seq)
        .all()
    )
    names = []
    for item in items:
        name = item.name_cn or ""
        if name and name not in names:
            names.append(name)
    return "、".join(names)[:500]


def _fill_invoice_from_customs(db, user, company_id, row, invoice, creating):
    row.invoice_no = invoice.invoice_no
    row.customs_invoice_id = invoice.id
    row.contract_no = (invoice.contract_no or "")[:64]
    linked = q(db, NumberContract, company_id).filter(NumberContract.contract_no == row.contract_no).first() if row.contract_no else None
    row.number_contract_id = linked.id if linked else row.number_contract_id
    content = _invoice_content(db, company_id, invoice)
    if content:
        row.content = content
    row.bl_date = invoice.invoice_date
    row.price_term = (invoice.payment_terms or "")[:255]
    row.currency = invoice.currency or "CNY"
    row.amount_cny = invoice.total_amount or Decimal("0")
    row.amount_usd = invoice.total_usd or Decimal("0")
    row.exchange_rate = invoice.exchange_rate or Decimal("0")
    if invoice.invoice_date:
        row.exchange_month = f"{invoice.invoice_date.year:04d}-{invoice.invoice_date.month:02d}"
    row.po_no = (invoice.po_no or "")[:100]
    row.bl_no = (invoice.bl_no or "")[:100]
    if creating or not row.operator_name:
        row.operator_name = (getattr(user, "name", None) or user.employee_id or "")[:100]
    purchase = (
        db.query(Contract)
        .filter(Contract.company_id == company_id, Contract.contract_code == row.contract_no, Contract.deleted_at.is_(None))
        .first()
        if row.contract_no else None
    )
    if purchase and purchase.transport_mode in ("海运", "空运") and not row.transport_type:
        row.transport_type = purchase.transport_mode


def sync_customs_invoice(db, user, company_id, invoice, payload, allocated=None):
    linked = q(db, NumberInvoice, company_id).filter(NumberInvoice.customs_invoice_id == invoice.id).first()
    same = q(db, NumberInvoice, company_id).filter(NumberInvoice.invoice_no == invoice.invoice_no).first()
    if linked and same and linked.id != same.id:
        raise BizError("该发票号已存在于发票编号表")
    row = linked or same
    if row and row.customs_invoice_id and row.customs_invoice_id != invoice.id:
        raise BizError("该发票号已关联其他报关发票")
    if row and row.is_batch:
        raise BizError("该发票号属于批次编号，不能直接关联报关发票")
    creating = row is None
    if creating:
        row = NumberInvoice(invoice_no=invoice.invoice_no, customs_invoice_id=invoice.id)
        stamp_new(row, user, company_id)
        db.add(row)
        db.flush()
    if allocated:
        row.num_pool = allocated["pool"]
        row.num_seq = allocated["seq"]
        row.number_year = allocated["year"]
        row.number_rule = allocated["number_rule"]
        row.business_type = allocated["business_type"]
        row.transport_type = allocated["transport_type"]
    else:
        preferred = RULE_POOL.get((payload.get("number_rule") or "").strip()) or (row.num_pool if row.num_pool in INVOICE_POOLS else None)
        pool = _bind_pattern(
            db, company_id, row, invoice.invoice_no, INVOICE_POOLS,
            preferred=preferred, self_invoice_id=row.id,
        )
        if pool:
            row.number_rule = POOL_RULE[pool]
            row.business_type = POOL_BUSINESS[pool]
            row.transport_type = POOL_TRANSPORT[pool]
        elif payload.get("number_rule") in RULE_POOL and not row.number_rule:
            row.number_rule = payload.get("number_rule")
    _fill_invoice_from_customs(db, user, company_id, row, invoice, creating)
    if not creating:
        bump(row, user.employee_id)
    op_log(db, user, company_id, "回写发票编号", "number_invoice", row.id, {"code": invoice.invoice_no})
    return row


def refresh_customs_invoice(db, user, company_id, invoice):
    row = q(db, NumberInvoice, company_id).filter(NumberInvoice.customs_invoice_id == invoice.id).first()
    if row is None:
        return None
    _fill_invoice_from_customs(db, user, company_id, row, invoice, False)
    bump(row, user.employee_id)
    return row


def detach_customs_invoice(db, user, company_id, invoice):
    row = q(db, NumberInvoice, company_id).filter(NumberInvoice.customs_invoice_id == invoice.id).first()
    if row is None and invoice.invoice_no:
        found = q(db, NumberInvoice, company_id).filter(NumberInvoice.invoice_no == invoice.invoice_no).first()
        if found and found.customs_invoice_id in (None, invoice.id):
            row = found
    if row is None:
        return
    if row.is_batch:
        raise BizError("该报关发票关联了批次发票编号，请先在发票编号中删除")
    release_number(db, company_id, row.num_pool, row.num_seq)
    soft_delete(row, user.employee_id)
    db.flush()


def _contract_dict(db, row):
    purchase = db.get(Contract, row.purchase_contract_id) if row.purchase_contract_id else None
    if purchase and purchase.deleted_at:
        purchase = None
    return {
        "id": row.id,
        "version": row.version,
        "contract_no": row.contract_no,
        "business_type": row.business_type,
        "number_year": row.number_year,
        "product_name": row.product_name,
        "party_b": row.party_b,
        "party_a": row.party_a,
        "amount_cny": row.amount_cny,
        "sign_date": row.sign_date,
        "owner_id": row.owner_id or "",
        "owner_name": name_of(user_names(db, [row.owner_id]), row.owner_id),
        "manual_edited": bool(row.manual_edited),
        "purchase_contract_id": purchase.id if purchase else None,
        "purchase_code": purchase.contract_code if purchase else "",
        "linked_label": "已关联" if purchase else "未关联",
        "created_at": row.created_at,
    }


def _invoice_dict(db, row):
    customs = db.get(CustomsInvoice, row.customs_invoice_id) if row.customs_invoice_id else None
    if customs and customs.deleted_at:
        customs = None
    return {
        "id": row.id,
        "version": row.version,
        "invoice_no": row.invoice_no,
        "contract_no": row.contract_no,
        "number_contract_id": row.number_contract_id,
        "business_type": row.business_type,
        "number_rule": row.number_rule,
        "number_year": row.number_year,
        "content": row.content,
        "bl_date": row.bl_date,
        "price_term": row.price_term,
        "currency": row.currency,
        "amount_usd": row.amount_usd,
        "amount_cny": row.amount_cny,
        "exchange_rate": row.exchange_rate,
        "exchange_month": row.exchange_month,
        "po_no": row.po_no,
        "operator_name": row.operator_name,
        "transport_type": row.transport_type,
        "email_sent_date": row.email_sent_date,
        "remark": row.remark or "",
        "bl_no": row.bl_no,
        "is_batch": bool(row.is_batch),
        "is_batch_master": bool(row.is_batch_master),
        "batch_id": row.batch_id,
        "batch_prefix": row.batch_prefix,
        "batch_sub_no": row.batch_sub_no,
        "batch_label": "批次" if row.is_batch else "否",
        "manual_edited": bool(row.manual_edited),
        "customs_invoice_id": customs.id if customs else None,
        "linked_label": "已关联" if customs else "未关联",
        "created_at": row.created_at,
    }


def _list_order(model, params, *extra):
    """倒序按编号年份、顺序号从新到旧；正序相反。"""
    descending = (params.get("order") or "desc").strip().lower() != "asc"
    columns = [model.number_year, func.coalesce(model.num_seq, 0), *extra, model.id]
    if descending:
        return [column.desc() for column in columns]
    return [column.asc() for column in columns]


def list_contract_numbers(db, company_id, params):
    query = q(db, NumberContract, company_id)
    keyword = (params.get("keyword") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        matched = (
            (NumberContract.contract_no.like(like))
            | (NumberContract.product_name.like(like))
            | (NumberContract.party_b.like(like))
            | (NumberContract.party_a.like(like))
            | (NumberContract.owner_id.like(like))
        )
        owner_ids = [
            item[0]
            for item in db.query(SysUser.employee_id).filter(SysUser.deleted_at.is_(None), SysUser.name.like(like)).all()
        ]
        if owner_ids:
            matched = matched | NumberContract.owner_id.in_(owner_ids)
        query = query.filter(matched)
    if params.get("business_type"):
        query = query.filter(NumberContract.business_type == params.get("business_type"))
    if params.get("number_year"):
        query = query.filter(NumberContract.number_year == int(params.get("number_year")))
    total = query.count()
    page_no = max(int(params.get("page") or 1), 1)
    size = min(max(int(params.get("pageSize") or 20), 1), 200)
    rows = query.order_by(*_list_order(NumberContract, params)).offset((page_no - 1) * size).limit(size).all()
    return [_contract_dict(db, row) for row in rows], total, page_no, size


def list_invoice_numbers(db, company_id, params):
    query = q(db, NumberInvoice, company_id)
    keyword = (params.get("keyword") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (NumberInvoice.invoice_no.like(like))
            | (NumberInvoice.contract_no.like(like))
            | (NumberInvoice.content.like(like))
            | (NumberInvoice.po_no.like(like))
            | (NumberInvoice.bl_no.like(like))
        )
    if params.get("number_rule"):
        query = query.filter(NumberInvoice.number_rule == params.get("number_rule"))
    if params.get("number_year"):
        query = query.filter(NumberInvoice.number_year == int(params.get("number_year")))
    total = query.count()
    page_no = max(int(params.get("page") or 1), 1)
    size = min(max(int(params.get("pageSize") or 20), 1), 200)
    rows = query.order_by(*_list_order(NumberInvoice, params, func.coalesce(NumberInvoice.sub_seq, 0))).offset((page_no - 1) * size).limit(size).all()
    return [_invoice_dict(db, row) for row in rows], total, page_no, size


def resolve_owner(db, company_id, text, previous=None):
    """按员工编号或姓名确定归属人。空值表示不指定。"""
    text = (text or "").strip()
    if not text:
        return "", ""
    rows = db.query(SysUser).filter(
        SysUser.deleted_at.is_(None),
        (SysUser.employee_id == text) | (SysUser.name == text),
    ).all()
    by_id = [item for item in rows if item.employee_id == text]
    if by_id:
        user = by_id[0]
    else:
        named = [item for item in rows if item.name == text]
        if len(named) > 1:
            raise BizError("归属人姓名重复，请填写员工编号")
        if not named:
            raise BizError("归属人不存在或已停用")
        user = named[0]
    from .ops import _owner_ok
    checked = _owner_ok(db, company_id, user.employee_id, previous=previous or None)
    return checked.employee_id, checked.name or checked.employee_id


def _apply_owner(db, company_id, row, payload):
    raw = str(payload.get("owner_id") or "").strip()
    if not raw:
        raise BizError("请选择归属人")
    owner_id, _name = resolve_owner(db, company_id, raw, previous=row.owner_id)
    row.owner_id = owner_id


def _apply_contract_form(db, company_id, row, payload, linked_contract=None):
    _apply_owner(db, company_id, row, payload)
    if linked_contract is not None:
        if "product_name" in payload:
            linked_contract.subject_name = _clean(payload.get("product_name"), 200, "产品/合同名称")
        if payload.get("sign_date") not in (None,):
            linked_contract.sign_date = parse_date(payload.get("sign_date"))
        _fill_contract_fields(db, company_id, row, linked_contract)
        return
    row.product_name = _clean(payload.get("product_name"), 200, "产品/合同名称", required=True)
    row.party_b = _clean(payload.get("party_b"), 200, "乙方", required=True)
    row.party_a = _clean(payload.get("party_a") or party_a_name(db, company_id), 200, "甲方", required=True)
    row.amount_cny = round2(payload.get("amount_cny") or 0)
    row.sign_date = parse_date(payload.get("sign_date"))
    if row.num_pool:
        return
    business = (payload.get("business_type") or row.business_type or "锰矿").strip()
    if business not in CONTRACT_POOL:
        raise BizError("业务类型只支持锰矿或铝矿")
    row.business_type = business
    if payload.get("number_year") not in (None, ""):
        row.number_year = parse_year(payload.get("number_year"))


def create_contract_number(db, user, company_id, payload):
    business = (payload.get("business_type") or "锰矿").strip()
    if business not in CONTRACT_POOL:
        raise BizError("业务类型只支持锰矿或铝矿")
    year = parse_year(payload.get("number_year"))
    specified = _clean(payload.get("contract_no"), 64, "合同编号")
    allocated = None
    if specified:
        if number_exists(db, company_id, specified):
            raise BizError("编号已存在，请更换")
        number = specified
    else:
        allocated = allocate_number(db, company_id, CONTRACT_POOL[business], year)
        number = allocated["number"]
    row = NumberContract(contract_no=number, business_type=business, number_year=year)
    stamp_new(row, user, company_id)
    db.add(row)
    db.flush()
    if allocated:
        row.num_pool = allocated["pool"]
        row.num_seq = allocated["seq"]
        row.number_year = allocated["year"]
    else:
        _bind_pattern(db, company_id, row, number, CONTRACT_POOLS, preferred=CONTRACT_POOL[business], self_contract_id=row.id)
        if row.num_pool:
            row.business_type = POOL_BUSINESS[row.num_pool]
            row.number_year = row.number_year or year
    _apply_contract_form(db, company_id, row, payload)
    row.contract_no = number
    op_log(db, user, company_id, "新增", "number_contract", row.id, {"code": number, "reused": bool(allocated and allocated["reused"])})
    return _contract_dict(db, row)


def update_contract_number(db, user, company_id, row, payload):
    from .util import ensure_version
    ensure_version(row, payload.get("version"))
    contract = None
    if row.purchase_contract_id:
        contract = db.get(Contract, row.purchase_contract_id)
        if contract is None or contract.deleted_at or contract.company_id != company_id:
            contract = None
    _apply_contract_form(db, company_id, row, payload, contract)
    bump(row, user.employee_id)
    op_log(db, user, company_id, "修改", "number_contract", row.id, {"code": row.contract_no})
    return _contract_dict(db, row)


def delete_contract_number(db, user, company_id, row):
    if row.purchase_contract_id:
        contract = db.get(Contract, row.purchase_contract_id)
        if contract and not contract.deleted_at:
            raise BizError("该编号已关联采购合同，请删除采购合同，编号会一起释放")
    release_number(db, company_id, row.num_pool, row.num_seq)
    code = row.contract_no
    soft_delete(row, user.employee_id)
    op_log(db, user, company_id, "删除", "number_contract", code, {})


def manual_contract_number(db, user, company_id, row, payload):
    new_no = _clean(payload.get("contract_no"), 64, "新编号", required=True)
    reason = _clean(payload.get("reason"), 200, "修改原因", required=True)
    if len(reason) < 2:
        raise BizError("请填写修改原因（2 到 200 个字）")
    if any(ch.isspace() for ch in new_no):
        raise BizError("新编号不能含空白")
    if new_no == row.contract_no:
        raise BizError("新编号与原编号相同")
    if number_exists(db, company_id, new_no, except_contract_id=row.id, except_purchase_id=row.purchase_contract_id):
        raise BizError("编号已存在，请更换")
    old = row.contract_no
    pool = _bind_pattern(
        db, company_id, row, new_no, CONTRACT_POOLS,
        preferred=row.num_pool if row.num_pool in CONTRACT_POOLS else CONTRACT_POOL.get(row.business_type),
        self_contract_id=row.id,
    )
    if pool:
        row.business_type = POOL_BUSINESS[pool]
    row.contract_no = new_no
    row.manual_edited = True
    if row.purchase_contract_id:
        contract = get_row(db, Contract, row.purchase_contract_id, company_id)
        contract.contract_code = new_no
        bump(contract, user.employee_id)
    bump(row, user.employee_id)
    db.add(NumberEditLog(
        company_id=company_id, target_type="contract", target_id=row.id, old_no=old, new_no=new_no,
        reason=reason, operator_name=getattr(user, "name", None) or user.employee_id,
        created_by=user.employee_id, updated_by=user.employee_id, created_at=now(), updated_at=now(), version=1,
    ))
    op_log(db, user, company_id, "手动改号", "number_contract", row.id, {"old": old, "new": new_no, "reason": reason})
    return _contract_dict(db, row)


def _refresh_batch_amounts(db, company_id, batch_id):
    children = (
        q(db, NumberInvoice, company_id)
        .filter(NumberInvoice.batch_id == batch_id, NumberInvoice.is_batch_master.is_(False))
        .all()
    )
    if not children:
        return
    usd = sum((D(row.amount_usd) for row in children), Decimal("0"))
    cny = sum((D(row.amount_cny) for row in children), Decimal("0"))
    master = (
        q(db, NumberInvoice, company_id)
        .filter(NumberInvoice.batch_id == batch_id, NumberInvoice.is_batch_master.is_(True))
        .first()
    )
    if master is None:
        return
    master.amount_usd = round2(usd)
    master.amount_cny = round2(cny)


def create_invoice_number(db, user, company_id, payload):
    mode = (payload.get("mode") or "plain").strip()
    if mode not in ("plain", "new_batch", "join_batch"):
        raise BizError("请选择登记方式")
    rule = (payload.get("number_rule") or "锰矿").strip()
    business = (payload.get("business_type") or "").strip()
    transport = (payload.get("transport_type") or "").strip()
    if rule in RULE_POOL:
        business = business or POOL_BUSINESS[RULE_POOL[rule]]
        transport = transport or POOL_TRANSPORT[RULE_POOL[rule]]
    content = _clean(payload.get("content"), 500, "所含内容", required=mode != "new_batch")
    if mode == "new_batch" and not content:
        content = "批次"
    price_term = _clean(payload.get("price_term") or "FOB", 255, "价格条款")
    currency = (payload.get("currency") or "USD").strip()
    if currency not in ("CNY", "USD"):
        raise BizError("请选择结算币种")
    contract_no = _clean(payload.get("contract_no"), 64, "关联合同")
    number_contract_id = None
    if contract_no:
        linked = q(db, NumberContract, company_id).filter(NumberContract.contract_no == contract_no).first()
        number_contract_id = linked.id if linked else None
    elif str(payload.get("number_contract_id") or "").isdigit():
        linked = get_row(db, NumberContract, int(payload["number_contract_id"]), company_id)
        number_contract_id = linked.id
        contract_no = linked.contract_no
    allow_zero = mode == "new_batch"
    amounts = _amounts(payload, official_rate(db, company_id, payload.get("exchange_month")), allow_zero=allow_zero)
    reused = False
    batch_id = None
    prefix = ""
    sub_no = ""
    sub_seq = None
    is_batch = mode != "plain"
    is_master = mode == "new_batch"
    pool = None
    seq = None
    year = parse_year(payload.get("number_year"))
    if mode == "join_batch":
        if not str(payload.get("batch_id") or "").isdigit():
            raise BizError("请选择要加入的批次")
        batch = get_row(db, NumberBatch, int(payload["batch_id"]), company_id)
        got = allocate_sub(db, company_id, batch.id, batch.prefix)
        number = got["number"]
        sub_no = got["sub_no"]
        sub_seq = got["seq"]
        reused = got["reused"]
        batch_id = batch.id
        prefix = batch.prefix
        rule = batch.number_rule
        business = batch.business_type
        transport = batch.transport_type
        year = batch.number_year
    else:
        _rule_of(business, transport, rule)
        got = allocate_number(db, company_id, RULE_POOL[rule], year)
        number = got["number"]
        pool = got["pool"]
        seq = got["seq"]
        year = got["year"]
        reused = got["reused"]
        if mode == "new_batch":
            prefix = number
            batch = NumberBatch(
                prefix=prefix, number_rule=rule, number_year=year, transport_type=transport,
                business_type=business, num_pool=pool, num_seq=seq,
            )
            stamp_new(batch, user, company_id)
            db.add(batch)
            db.flush()
            batch_id = batch.id
    row = NumberInvoice(
        invoice_no=number,
        number_contract_id=number_contract_id,
        contract_no=contract_no,
        business_type=business,
        number_rule=rule,
        number_year=year,
        num_pool=pool,
        num_seq=seq,
        content=content,
        bl_date=parse_date(payload.get("bl_date")),
        price_term=price_term,
        currency=currency,
        amount_usd=amounts["amount_usd"],
        amount_cny=amounts["amount_cny"],
        exchange_rate=amounts["exchange_rate"],
        exchange_month=amounts["exchange_month"],
        rate_adjusted=amounts["rate_adjusted"],
        po_no=_clean(payload.get("po_no"), 100, "PO"),
        operator_name=(getattr(user, "name", None) or user.employee_id or "")[:100],
        transport_type=transport,
        email_sent_date=parse_date(payload.get("email_sent_date")),
        remark=_clean(payload.get("remark"), 500, "备注"),
        bl_no=_clean(payload.get("bl_no"), 100, "提单号"),
        is_batch=is_batch,
        is_batch_master=is_master,
        batch_id=batch_id,
        batch_prefix=prefix,
        batch_sub_no=sub_no,
        sub_seq=sub_seq,
    )
    stamp_new(row, user, company_id)
    db.add(row)
    db.flush()
    if batch_id:
        _refresh_batch_amounts(db, company_id, batch_id)
    op_log(db, user, company_id, "新增", "number_invoice", row.id, {"code": number, "reused": reused, "batch": is_batch})
    return _invoice_dict(db, row)


def update_invoice_number(db, user, company_id, row, payload):
    from .util import ensure_version
    ensure_version(row, payload.get("version"))
    if row.customs_invoice_id:
        customs = db.get(CustomsInvoice, row.customs_invoice_id)
        if customs and not customs.deleted_at:
            if "remark" in payload:
                row.remark = _clean(payload.get("remark"), 500, "备注")
            if payload.get("email_sent_date") not in (None,):
                row.email_sent_date = parse_date(payload.get("email_sent_date"))
            _fill_invoice_from_customs(db, user, company_id, row, customs, False)
            bump(row, user.employee_id)
            return _invoice_dict(db, row)
    if row.is_batch_master:
        raise BizError("批次前缀按批次规则管理，金额由小批发票汇总")
    content = _clean(payload.get("content", row.content), 500, "所含内容", required=True)
    currency = (payload.get("currency") or row.currency or "USD").strip()
    if currency not in ("CNY", "USD"):
        raise BizError("请选择结算币种")
    amounts = _amounts(payload, official_rate(db, company_id, payload.get("exchange_month") or row.exchange_month), allow_zero=bool(row.is_batch))
    row.content = content
    row.bl_date = parse_date(payload.get("bl_date"))
    row.price_term = _clean(payload.get("price_term") or row.price_term, 255, "价格条款")
    row.currency = currency
    row.amount_usd = amounts["amount_usd"]
    row.amount_cny = amounts["amount_cny"]
    row.exchange_rate = amounts["exchange_rate"]
    row.exchange_month = amounts["exchange_month"]
    row.rate_adjusted = amounts["rate_adjusted"]
    row.po_no = _clean(payload.get("po_no"), 100, "PO")
    row.email_sent_date = parse_date(payload.get("email_sent_date"))
    row.remark = _clean(payload.get("remark"), 500, "备注")
    row.bl_no = _clean(payload.get("bl_no"), 100, "提单号")
    contract_no = _clean(payload.get("contract_no", row.contract_no), 64, "关联合同")
    row.contract_no = contract_no
    if contract_no:
        linked = q(db, NumberContract, company_id).filter(NumberContract.contract_no == contract_no).first()
        row.number_contract_id = linked.id if linked else None
    bump(row, user.employee_id)
    if row.batch_id:
        _refresh_batch_amounts(db, company_id, row.batch_id)
    op_log(db, user, company_id, "修改", "number_invoice", row.id, {"code": row.invoice_no})
    return _invoice_dict(db, row)


def delete_invoice_number(db, user, company_id, row):
    if row.customs_invoice_id:
        customs = db.get(CustomsInvoice, row.customs_invoice_id)
        if customs and not customs.deleted_at:
            raise BizError("该编号已关联报关发票，请删除报关发票，编号会一起释放")
    if row.is_batch_master:
        child = (
            q(db, NumberInvoice, company_id)
            .filter(NumberInvoice.batch_id == row.batch_id, NumberInvoice.is_batch_master.is_(False))
            .first()
        )
        if child:
            raise BizError("请先删除该批次下的小批发票")
        release_number(db, company_id, row.num_pool, row.num_seq)
        if row.batch_id:
            batch = db.get(NumberBatch, row.batch_id)
            if batch:
                for slot in db.query(NumberBatchSlot).filter(NumberBatchSlot.batch_id == batch.id).all():
                    db.delete(slot)
                soft_delete(batch, user.employee_id)
        soft_delete(row, user.employee_id)
        return
    if row.batch_id and row.sub_seq:
        release_sub(db, row.batch_id, row.sub_seq)
        batch_id = row.batch_id
        soft_delete(row, user.employee_id)
        db.flush()
        _refresh_batch_amounts(db, company_id, batch_id)
        return
    release_number(db, company_id, row.num_pool, row.num_seq)
    soft_delete(row, user.employee_id)
    op_log(db, user, company_id, "删除", "number_invoice", row.invoice_no, {})


def manual_invoice_number(db, user, company_id, row, payload):
    if row.is_batch:
        raise BizError("批次发票编号不支持手动编辑，请删除后重新登记")
    new_no = _clean(payload.get("invoice_no"), 80, "新编号", required=True)
    reason = _clean(payload.get("reason"), 200, "修改原因", required=True)
    if len(reason) < 2:
        raise BizError("请填写修改原因（2 到 200 个字）")
    if any(ch.isspace() for ch in new_no):
        raise BizError("新编号不能含空白")
    if new_no == row.invoice_no:
        raise BizError("新编号与原编号相同")
    if number_exists(db, company_id, new_no, except_invoice_id=row.id, except_customs_id=row.customs_invoice_id):
        raise BizError("编号已存在，请更换")
    old = row.invoice_no
    preferred = row.num_pool if row.num_pool in INVOICE_POOLS else RULE_POOL.get(row.number_rule)
    pool = _bind_pattern(db, company_id, row, new_no, INVOICE_POOLS, preferred=preferred, self_invoice_id=row.id)
    if pool:
        row.number_rule = POOL_RULE[pool]
        row.business_type = POOL_BUSINESS[pool]
        row.transport_type = POOL_TRANSPORT[pool]
    row.invoice_no = new_no
    row.manual_edited = True
    if row.customs_invoice_id:
        customs = get_row(db, CustomsInvoice, row.customs_invoice_id, company_id)
        customs.invoice_no = new_no
        bump(customs, user.employee_id)
        for item in q(db, CustomsInvoiceItem, company_id).filter(CustomsInvoiceItem.invoice_id == customs.id).all():
            item.invoice_no = new_no
    bump(row, user.employee_id)
    db.add(NumberEditLog(
        company_id=company_id, target_type="invoice", target_id=row.id, old_no=old, new_no=new_no,
        reason=reason, operator_name=getattr(user, "name", None) or user.employee_id,
        created_by=user.employee_id, updated_by=user.employee_id, created_at=now(), updated_at=now(), version=1,
    ))
    op_log(db, user, company_id, "手动改号", "number_invoice", row.id, {"old": old, "new": new_no, "reason": reason})
    return _invoice_dict(db, row)


def recent_batches(db, company_id):
    rows = q(db, NumberBatch, company_id).order_by(NumberBatch.id.desc()).limit(30).all()
    return [
        {
            "id": row.id,
            "prefix": row.prefix,
            "number_rule": row.number_rule,
            "number_year": row.number_year,
            "business_type": row.business_type,
            "transport_type": row.transport_type,
        }
        for row in rows
    ]


def floor_state(db, company_id, pool):
    year = default_number_year()
    floor = pool_floor(db, company_id, pool)
    try:
        preview = preview_number(db, company_id, pool, year)["number"]
    except BizError:
        preview = ""
    return {"pool": pool, "label": POOL_LABELS[pool], "floor": floor, "preview": preview, "year": year}


def meta(db, company_id):
    return {
        "years": year_options(),
        "default_year": default_number_year(),
        "party_a": party_a_name(db, company_id),
        "contract_types": [{"value": key, "pool": pool, "label": POOL_LABELS[pool]} for key, pool in CONTRACT_POOL.items()],
        "invoice_rules": [{"value": key, "pool": pool, "label": POOL_LABELS[pool]} for key, pool in RULE_POOL.items()],
        "contract_floors": [floor_state(db, company_id, pool) for pool in CONTRACT_POOL.values()],
        "invoice_floors": [floor_state(db, company_id, pool) for pool in RULE_POOL.values()],
        "batches": recent_batches(db, company_id),
    }
