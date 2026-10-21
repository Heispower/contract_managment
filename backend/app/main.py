import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config
from .database import (
    Base,
    ensure_company_columns,
    ensure_customs_form_columns,
    ensure_hs_columns,
    ensure_number_columns,
    ensure_item_category_columns,
    ensure_party_columns,
    ensure_project_columns,
    get_engine,
    get_session,
    init_engine,
)
from .errors import BizError
from .response import fail
from .routers import api
from .services.export_profile import ensure_export_profiles, prepare_export_table
from .services.seed import seed_system
from .services.calc import realign_header_ex_tax
from .services.util import purge_deleted_rows

logger = logging.getLogger("contract")

app = FastAPI(title="合同管理系统", version="2.5.3")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Download-Name"],
)
app.include_router(api)


def _detail_text(detail) -> str:
    if detail is None:
        return "请求失败"
    if isinstance(detail, str):
        text = detail.strip()
        return text or "请求失败"
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(part) for part in item.get("loc") or [] if part not in ("body", "query"))
                msg = str(item.get("msg") or "").strip()
                parts.append(f"{loc}：{msg}" if loc and msg else msg or loc)
            else:
                parts.append(str(item).strip())
        text = "；".join(part for part in parts if part)
        return text or "请求参数不正确"
    return str(detail).strip() or "请求失败"


def _unexpected_text(exc: Exception) -> str:
    orig = getattr(exc, "orig", None)
    detail = str(orig).strip() if orig is not None else str(exc).strip()
    if not detail:
        detail = exc.__class__.__name__
    if len(detail) > 500:
        detail = detail[:500] + "…"
    return f"系统错误：{detail}"


@app.exception_handler(BizError)
def handle_biz(_request, exc: BizError):
    return fail(exc)


@app.exception_handler(RequestValidationError)
def handle_validation(_request, exc: RequestValidationError):
    return JSONResponse({"code": 422, "message": _detail_text(exc.errors()), "data": {"errors": _detail_text(exc.errors())}}, status_code=422)


@app.exception_handler(StarletteHTTPException)
def handle_http(_request, exc: StarletteHTTPException):
    message = _detail_text(exc.detail)
    if exc.status_code == 404 and message == "Not Found":
        message = "接口不存在"
    elif exc.status_code == 405 and message == "Method Not Allowed":
        message = "请求方法不正确"
    return JSONResponse({"code": exc.status_code, "message": message, "data": None}, status_code=exc.status_code)


@app.exception_handler(Exception)
def handle_unexpected(_request, exc: Exception):
    logger.exception("未处理异常")
    return JSONResponse({"code": 500, "message": _unexpected_text(exc), "data": {"type": exc.__class__.__name__}}, status_code=500)


@app.on_event("startup")
def startup():
    init_engine(config.DB_PATH)
    Base.metadata.create_all(get_engine())
    ensure_company_columns()
    ensure_party_columns()
    ensure_project_columns()
    ensure_item_category_columns()
    ensure_customs_form_columns()
    ensure_hs_columns()
    ensure_number_columns()
    prepare_export_table()
    db = get_session()
    try:
        purge_deleted_rows(db)
        realign_header_ex_tax(db)
        seed_system(db)
        from .services.numbering import ensure_number_rules
        ensure_number_rules(db)
        from .services.customs import ensure_deepseek_settings
        ensure_deepseek_settings(db)
        ensure_export_profiles(db)
        from .services.customs import backfill_from_wms, repair_orphan_chain
        backfill_from_wms(db)
        repair_orphan_chain(db)
        db.commit()
    finally:
        db.close()


DIST = Path(config.ROOT) / "frontend" / "dist"
if DIST.exists():
    assets = DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        target = DIST / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
