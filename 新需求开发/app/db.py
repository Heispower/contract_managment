import json
import os
import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash

from app.utils import now_str

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login_name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'user', 'viewer')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'disabled')),
    allow_rate INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_no TEXT NOT NULL,
    business_type TEXT NOT NULL,
    number_year INTEGER NOT NULL,
    num_pool TEXT,
    num_seq INTEGER,
    product_name TEXT NOT NULL,
    party_b TEXT NOT NULL,
    party_a TEXT NOT NULL,
    amount_cny TEXT NOT NULL,
    sign_date TEXT NOT NULL,
    manual_edited INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER NOT NULL,
    updated_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    deleted_by INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_contract_no
    ON contracts(contract_no) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_contracts_list
    ON contracts(deleted_at, created_at);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prefix TEXT NOT NULL,
    number_rule TEXT NOT NULL,
    number_year INTEGER NOT NULL,
    transport_type TEXT NOT NULL,
    business_type TEXT NOT NULL,
    num_pool TEXT,
    num_seq INTEGER,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    deleted_by INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_batch_prefix
    ON batches(prefix) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no TEXT NOT NULL,
    contract_id INTEGER,
    business_type TEXT NOT NULL,
    number_rule TEXT NOT NULL,
    number_year INTEGER NOT NULL,
    num_pool TEXT,
    num_seq INTEGER,
    content TEXT NOT NULL,
    bl_date TEXT,
    price_term TEXT NOT NULL,
    currency TEXT NOT NULL,
    amount_usd TEXT NOT NULL,
    amount_cny TEXT NOT NULL,
    exchange_rate TEXT NOT NULL,
    exchange_month TEXT NOT NULL,
    rate_adjusted INTEGER NOT NULL DEFAULT 0,
    po_no TEXT,
    operator_id INTEGER NOT NULL,
    operator_name TEXT NOT NULL,
    transport_type TEXT NOT NULL,
    email_sent_date TEXT,
    remark TEXT,
    bl_no TEXT,
    is_batch INTEGER NOT NULL DEFAULT 0,
    is_batch_master INTEGER NOT NULL DEFAULT 0,
    batch_id INTEGER,
    batch_prefix TEXT,
    batch_sub_no TEXT,
    sub_seq INTEGER,
    manual_edited INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER NOT NULL,
    updated_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    deleted_by INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_no
    ON invoices(invoice_no) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_invoices_list
    ON invoices(deleted_at, created_at);
CREATE INDEX IF NOT EXISTS idx_invoices_batch
    ON invoices(batch_id, deleted_at);

CREATE TABLE IF NOT EXISTS number_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_key TEXT NOT NULL,
    seq INTEGER NOT NULL,
    status TEXT NOT NULL,
    year INTEGER,
    number TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(pool_key, seq)
);

CREATE INDEX IF NOT EXISTS idx_slots_pool
    ON number_slots(pool_key, status, seq);

CREATE TABLE IF NOT EXISTS batch_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    status TEXT NOT NULL,
    number TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(batch_id, seq)
);

CREATE TABLE IF NOT EXISTS exchange_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month TEXT NOT NULL UNIQUE,
    source_currency TEXT NOT NULL DEFAULT 'USD',
    target_currency TEXT NOT NULL DEFAULT 'CNY',
    rate TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    maintainer_id INTEGER NOT NULL,
    maintainer_name TEXT NOT NULL,
    remark TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS number_edit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    old_no TEXT NOT NULL,
    new_no TEXT NOT NULL,
    reason TEXT NOT NULL,
    operator_id INTEGER NOT NULL,
    operator_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    login_name TEXT,
    display_name TEXT,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id INTEGER,
    summary TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_logs_created ON operation_logs(created_at);
"""


def db_path():
    return os.environ.get("APP_DB") or str(DATA_DIR / "app.db")


def connect():
    path = db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=8000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _seed(conn)
        from app.utils import refresh_open_batch_amounts

        refresh_open_batch_amounts(conn)
    finally:
        conn.close()


def _seed(conn):
    ts = now_str()
    exists = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    if not exists:
        conn.execute(
            """INSERT INTO users
               (login_name, display_name, password_hash, role, status, allow_rate, created_at, updated_at)
               VALUES (?, ?, ?, 'admin', 'active', 1, ?, ?)""",
            ("admin", "系统管理员", generate_password_hash("admin123"), ts, ts),
        )
    row = conn.execute(
        "SELECT key FROM settings WHERE key='allow_user_manual_edit'"
    ).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('allow_user_manual_edit', '0')"
        )


def get_db():
    from flask import g

    if "db" not in g:
        g.db = connect()
    return g.db


def begin_immediate(db):
    db.execute("BEGIN IMMEDIATE")


def safe_rollback(db):
    try:
        db.rollback()
    except sqlite3.OperationalError:
        pass


def get_setting(key, default=None):
    row = get_db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    return row["value"]


def log_op(db, user, action, summary, target_type=None, target_id=None, detail=None):
    payload = None
    if detail is not None:
        payload = json.dumps(detail, ensure_ascii=False)
    db.execute(
        """INSERT INTO operation_logs
           (user_id, login_name, display_name, action, target_type, target_id, summary, detail, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            None if user is None else user["id"],
            None if user is None else user["login_name"],
            None if user is None else user["display_name"],
            action,
            target_type,
            target_id,
            summary,
            payload,
            now_str(),
        ),
    )
