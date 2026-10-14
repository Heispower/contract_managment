import logging
import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

from app.auth import can_manual, can_mutate, can_rate, can_write, current_user, new_csrf
from app.db import LOG_DIR, ROOT, get_db, init_db
from app.utils import ROLE_LABELS, STATUS_LABELS, keep_qs, lan_ipv4, listen_port

NAV_ITEMS = [
    {"endpoint": "contracts.index", "label": "合同登记"},
    {"endpoint": "invoices.index", "label": "发票登记"},
    {"endpoint": "batches.index", "label": "批次发货"},
    {
        "label": "基础数据维护",
        "children": [
            {"endpoint": "rates.index", "label": "汇率维护", "need": "rate"},
            {"endpoint": "sequences.index", "label": "当前序号", "need": "admin"},
        ],
    },
    {"endpoint": "users.index", "label": "用户管理", "need": "admin"},
    {"endpoint": "logs.index", "label": "操作日志", "need": "admin"},
]


def _load_secret():
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    path = ROOT / "data" / "secret.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    path.write_text(key, encoding="utf-8")
    return key


def _nav_allowed(user, need):
    if not need:
        return True
    if not user:
        return False
    if need == "admin":
        return user["role"] == "admin"
    if need == "rate":
        return can_rate(user)
    return False


def _navigation(user, endpoint):
    items = []
    active = ""
    for entry in NAV_ITEMS:
        children = entry.get("children")
        if children:
            visible = []
            group_active = False
            for child in children:
                if not _nav_allowed(user, child.get("need")):
                    continue
                if endpoint.startswith(child["endpoint"].split(".")[0]):
                    active = child["endpoint"]
                    group_active = True
                visible.append({"endpoint": child["endpoint"], "label": child["label"]})
            if visible:
                items.append({"label": entry["label"], "children": visible, "active": group_active})
            continue
        if not _nav_allowed(user, entry.get("need")):
            continue
        if endpoint.startswith(entry["endpoint"].split(".")[0]):
            active = entry["endpoint"]
        items.append({"endpoint": entry["endpoint"], "label": entry["label"]})
    return items, active


def _logger():
    logger = logging.getLogger("invoiceapp")
    if logger.handlers:
        return logger
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(
        SECRET_KEY=_load_secret(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
        SESSION_REFRESH_EACH_REQUEST=True,
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        TEMPLATES_AUTO_RELOAD=True,
        JSON_AS_ASCII=False,
    )
    app.json.ensure_ascii = False
    init_db()
    logger = _logger()

    @app.before_request
    def prepare_request():
        if "csrf" not in session:
            new_csrf()
        if request.method == "POST" and not app.config.get("TESTING_SKIP_CSRF"):
            token = request.form.get("csrf") or request.headers.get("X-CSRF-Token")
            expected = session.get("csrf", "")
            if not token or not secrets.compare_digest(token, expected):
                abort(400, description="页面已过期，请返回后重新提交。")
        session.permanent = True

    @app.teardown_appcontext
    def close_db(_exc):
        db = g_pop_db()
        if db is not None:
            db.close()

    @app.context_processor
    def inject_globals():
        user = current_user()
        items, active = _navigation(user, request.endpoint or "")
        return {
            "me": user,
            "csrf_token": session.get("csrf", ""),
            "can_write": can_write(user),
            "can_manual": can_manual(user),
            "can_rate": can_rate(user),
            "can_mutate_row": lambda record: can_mutate(user, record),
            "is_admin": bool(user and user["role"] == "admin"),
            "keep": keep_qs,
            "nav_items": items,
            "active_nav": active,
            "role_labels": ROLE_LABELS,
            "status_labels": STATUS_LABELS,
            "lan_hosts": lan_ipv4(),
            "lan_port": listen_port(),
        }

    @app.template_filter("money")
    def money_filter(value):
        if value is None or value == "":
            return ""
        from decimal import Decimal, InvalidOperation

        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return value
        return f"{number:,.2f}"

    @app.template_filter("ratefmt")
    def rate_filter(value):
        if value is None or value == "":
            return ""
        from decimal import Decimal, InvalidOperation

        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return value
        return f"{number:.6f}"

    @app.route("/")
    def home():
        if current_user():
            return redirect(url_for("contracts.index"))
        return redirect(url_for("auth.login"))

    @app.errorhandler(400)
    def bad_request(error):
        message = getattr(error, "description", None) or "请求无效。"
        return render_template("error.html", title="无法提交", message=message), 400

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", title="没有权限", message="当前账号不能执行这个操作。"), 403

    @app.errorhandler(413)
    def too_large(_error):
        return render_template("error.html", title="文件过大", message="上传文件不能超过 16MB。"), 413

    @app.errorhandler(404)
    def missing(_error):
        return render_template("error.html", title="页面不存在", message="没有找到对应页面。"), 404

    @app.errorhandler(Exception)
    def unhandled(error):
        if isinstance(error, HTTPException):
            return error
        logger.exception("unhandled error")
        if app.testing:
            return render_template("error.html", title="系统错误", message=f"{type(error).__name__}: {error}"), 500
        return render_template("error.html", title="系统错误", message="系统处理失败，请稍后重试。"), 500

    from app.blueprints.auth_bp import bp as auth_bp
    from app.blueprints.batch_bp import bp as batch_bp
    from app.blueprints.contract_bp import bp as contract_bp
    from app.blueprints.invoice_bp import bp as invoice_bp
    from app.blueprints.log_bp import bp as log_bp
    from app.blueprints.rate_bp import bp as rate_bp
    from app.blueprints.sequence_bp import bp as sequence_bp
    from app.blueprints.user_bp import bp as user_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(contract_bp)
    app.register_blueprint(invoice_bp)
    app.register_blueprint(batch_bp)
    app.register_blueprint(rate_bp)
    app.register_blueprint(sequence_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(log_bp)
    app.logger_instance = logger
    return app


def g_pop_db():
    from flask import g

    return g.pop("db", None)


def safe_next(raw):
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return url_for("contracts.index")
    return raw
