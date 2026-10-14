import re

from app.utils import now_str


CONTRACT_POOL = {
    "锰矿": "contract_mn",
    "铝矿": "contract_al",
}

RULE_POOL = {
    "铝矿海运": "invoice_al_sea",
    "铝矿空运": "invoice_al_air",
    "锰矿": "invoice_mn",
}

POOL_LABELS = {
    "contract_mn": "锰矿合同",
    "contract_al": "铝矿合同",
    "invoice_al_sea": "铝矿海运",
    "invoice_al_air": "铝矿空运",
    "invoice_mn": "锰矿发票",
}

PATTERNS = {
    "contract_mn": re.compile(r"^BMI-GMI-(\d{4})(\d{3,})$"),
    "contract_al": re.compile(r"^BMGG-MAZ-(\d{2})(\d{3,})$"),
    "invoice_al_sea": re.compile(r"^BMI-BMGGMAZ-(\d{2})(\d{3,})S$"),
    "invoice_al_air": re.compile(r"^BMI-BMGGMAZ-(\d{2})(\d{3,})A$"),
    "invoice_mn": re.compile(r"^(\d{4})(\d{4,})$"),
}

TWO_DIGIT_YEAR = {"contract_al", "invoice_al_sea", "invoice_al_air"}


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
    raise ValueError("未知编号规则")


def format_sub_no(seq):
    seq = int(seq)
    if seq < 1000:
        return f"-{seq:03d}"
    return f"-{seq}"


def parse_pool_number(pool, number):
    pattern = PATTERNS.get(pool)
    if not pattern or number is None:
        return None
    matched = pattern.match(str(number).strip())
    if not matched:
        return None
    year_raw, seq_raw = matched.group(1), matched.group(2)
    seq = int(seq_raw)
    if seq < 1:
        return None
    if pool in TWO_DIGIT_YEAR:
        year = 2000 + int(year_raw)
    else:
        year = int(year_raw)
    if year < 2000 or year > 2099:
        return None
    return year, seq


def matches_any_pattern(number):
    text = "" if number is None else str(number).strip()
    return any(parse_pool_number(pool, text) for pool in PATTERNS)


def number_exists(db, number, except_contract_id=None, except_invoice_id=None, except_batch_id=None):
    row = db.execute(
        "SELECT id FROM contracts WHERE contract_no=? AND deleted_at IS NULL",
        (number,),
    ).fetchone()
    if row and row["id"] != except_contract_id:
        return True
    row = db.execute(
        "SELECT id FROM invoices WHERE invoice_no=? AND deleted_at IS NULL",
        (number,),
    ).fetchone()
    if row and row["id"] != except_invoice_id:
        return True
    row = db.execute(
        "SELECT id FROM batches WHERE prefix=? AND deleted_at IS NULL",
        (number,),
    ).fetchone()
    if row and row["id"] != except_batch_id:
        return True
    return False


def _candidate_seqs(free_seqs, max_seq, limit=40):
    seqs = []
    seen = set()
    for seq in list(free_seqs) + list(range(max_seq + 1, max_seq + 1 + limit)):
        if seq not in seen and seq >= 1:
            seen.add(seq)
            seqs.append(seq)
    return seqs


def pool_floor(db, pool):
    """该序号及更小的号视为历史号：不自动分配，删除后也不回收。"""
    row = db.execute(
        "SELECT value FROM settings WHERE key=?",
        (f"seq_floor:{pool}",),
    ).fetchone()
    if not row:
        return 0
    text = str(row["value"] or "").strip()
    if not text.isdigit():
        return 0
    return int(text)


def parse_floor_value(pool, raw):
    text = "" if raw is None else str(raw).strip()
    if not text:
        raise ValueError("请填写最新顺序号，或该规则的完整编号")
    parsed = parse_pool_number(pool, text)
    if parsed:
        return parsed[1]
    if matches_any_pattern(text):
        raise ValueError("这个编号不属于当前规则")
    if not text.isdigit():
        raise ValueError("请填写顺序号，或该规则的完整编号")
    seq = int(text)
    if seq < 1 or seq > 999999:
        raise ValueError("顺序号需在 1 到 999999 之间")
    return seq


def set_pool_floor(db, pool, seq):
    seq = int(seq)
    if seq < 0 or seq > 999999:
        raise ValueError("顺序号需在 0 到 999999 之间")
    db.execute(
        """INSERT INTO settings (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (f"seq_floor:{pool}", str(seq)),
    )
    ts = now_str()
    if seq > 0:
        db.execute(
            """UPDATE number_slots
               SET status='held', year=NULL, number=NULL, updated_at=?
               WHERE pool_key=? AND status='free' AND seq<=?""",
            (ts, pool, seq),
        )
    db.execute(
        """UPDATE number_slots
           SET status='free', updated_at=?
           WHERE pool_key=? AND status='held' AND seq>?""",
        (ts, pool, seq),
    )


def _free_and_max(db, pool):
    floor = pool_floor(db, pool)
    free_rows = db.execute(
        "SELECT seq FROM number_slots WHERE pool_key=? AND status='free' AND seq>? ORDER BY seq",
        (pool, floor),
    ).fetchall()
    max_seq = db.execute(
        "SELECT COALESCE(MAX(seq), 0) AS m FROM number_slots WHERE pool_key=?",
        (pool,),
    ).fetchone()["m"]
    return [row["seq"] for row in free_rows], max(int(max_seq), floor)


def preview_number(db, pool, year):
    free_seqs, max_seq = _free_and_max(db, pool)
    for seq in _candidate_seqs(free_seqs, max_seq):
        number = format_number(pool, year, seq)
        if number_exists(db, number):
            continue
        return {"number": number, "seq": seq, "reused": seq in free_seqs, "pool": pool}
    raise ValueError("编号生成失败")


def allocate_number(db, pool, year):
    """在调用方已开启的事务中分配编号。优先最小空闲顺序号。"""
    free_seqs, max_seq = _free_and_max(db, pool)
    free_set = set(free_seqs)
    ts = now_str()
    for seq in _candidate_seqs(free_seqs, max_seq):
        number = format_number(pool, year, seq)
        if number_exists(db, number):
            continue
        if seq in free_set:
            cur = db.execute(
                """UPDATE number_slots
                   SET status='used', year=?, number=?, updated_at=?
                   WHERE pool_key=? AND seq=? AND status='free'""",
                (year, number, ts, pool, seq),
            )
            if cur.rowcount != 1:
                continue
            reused = True
        else:
            try:
                db.execute(
                    """INSERT INTO number_slots
                       (pool_key, seq, status, year, number, updated_at)
                       VALUES (?, ?, 'used', ?, ?, ?)""",
                    (pool, seq, year, number, ts),
                )
            except Exception:
                continue
            reused = False
        return {"number": number, "seq": seq, "reused": reused, "pool": pool}
    raise ValueError("编号生成失败，请重试")


def release_number(db, pool, seq):
    if not pool or not seq:
        return
    status = "held" if int(seq) <= pool_floor(db, pool) else "free"
    db.execute(
        """UPDATE number_slots
           SET status=?, year=NULL, number=NULL, updated_at=?
           WHERE pool_key=? AND seq=?""",
        (status, now_str(), pool, seq),
    )


def slot_blocked(db, pool, seq, self_contract_id=None, self_invoice_id=None):
    contracts = db.execute(
        """SELECT id FROM contracts
           WHERE num_pool=? AND num_seq=? AND deleted_at IS NULL""",
        (pool, seq),
    ).fetchall()
    for row in contracts:
        if row["id"] != self_contract_id:
            return True
    invoices = db.execute(
        """SELECT id FROM invoices
           WHERE num_pool=? AND num_seq=? AND deleted_at IS NULL""",
        (pool, seq),
    ).fetchall()
    for row in invoices:
        if row["id"] != self_invoice_id:
            return True
    return False


def occupy_slot(db, pool, seq, year, number):
    ts = now_str()
    existing = db.execute(
        "SELECT seq, status FROM number_slots WHERE pool_key=?",
        (pool,),
    ).fetchall()
    have = {row["seq"]: row["status"] for row in existing}
    floor = pool_floor(db, pool)
    for index in range(1, int(seq)):
        if index not in have:
            gap_status = "held" if index <= floor else "free"
            db.execute(
                """INSERT INTO number_slots
                   (pool_key, seq, status, year, number, updated_at)
                   VALUES (?, ?, ?, NULL, NULL, ?)""",
                (pool, index, gap_status, ts),
            )
    if seq in have:
        db.execute(
            """UPDATE number_slots
               SET status='used', year=?, number=?, updated_at=?
               WHERE pool_key=? AND seq=?""",
            (year, number, ts, pool, seq),
        )
    else:
        db.execute(
            """INSERT INTO number_slots
               (pool_key, seq, status, year, number, updated_at)
               VALUES (?, ?, 'used', ?, ?, ?)""",
            (pool, seq, year, number, ts),
        )


def _sub_candidates(db, batch_id):
    free_rows = db.execute(
        "SELECT seq FROM batch_slots WHERE batch_id=? AND status='free' ORDER BY seq",
        (batch_id,),
    ).fetchall()
    max_seq = db.execute(
        "SELECT COALESCE(MAX(seq), 0) AS m FROM batch_slots WHERE batch_id=?",
        (batch_id,),
    ).fetchone()["m"]
    free_seqs = [row["seq"] for row in free_rows]
    return free_seqs, int(max_seq)


def preview_sub(db, batch_id, prefix):
    free_seqs, max_seq = _sub_candidates(db, batch_id)
    for seq in _candidate_seqs(free_seqs, max_seq):
        sub_no = format_sub_no(seq)
        number = f"{prefix}{sub_no}"
        if number_exists(db, number, except_batch_id=batch_id):
            continue
        return {"number": number, "sub_no": sub_no, "seq": seq, "reused": seq in free_seqs}
    raise ValueError("小批号生成失败")


def allocate_sub(db, batch_id, prefix):
    free_seqs, max_seq = _sub_candidates(db, batch_id)
    free_set = set(free_seqs)
    ts = now_str()
    for seq in _candidate_seqs(free_seqs, max_seq):
        sub_no = format_sub_no(seq)
        number = f"{prefix}{sub_no}"
        if number_exists(db, number, except_batch_id=batch_id):
            continue
        if seq in free_set:
            cur = db.execute(
                """UPDATE batch_slots
                   SET status='used', number=?, updated_at=?
                   WHERE batch_id=? AND seq=? AND status='free'""",
                (number, ts, batch_id, seq),
            )
            if cur.rowcount != 1:
                continue
            reused = True
        else:
            try:
                db.execute(
                    """INSERT INTO batch_slots (batch_id, seq, status, number, updated_at)
                       VALUES (?, ?, 'used', ?, ?)""",
                    (batch_id, seq, number, ts),
                )
            except Exception:
                continue
            reused = False
        return {"number": number, "sub_no": sub_no, "seq": seq, "reused": reused}
    raise ValueError("小批号生成失败，请重试")


def release_sub(db, batch_id, seq):
    if not batch_id or not seq:
        return
    db.execute(
        """UPDATE batch_slots
           SET status='free', number=NULL, updated_at=?
           WHERE batch_id=? AND seq=?""",
        (now_str(), batch_id, seq),
    )
