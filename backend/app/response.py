import json
from datetime import date, datetime
from decimal import Decimal

from fastapi.responses import JSONResponse

from .errors import BizError


def _convert(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dict):
        return {key: _convert(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_convert(item) for item in value]
    return value


def ok(data=None, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": _convert(data)})


def page(items, total, page_no, page_size, **extra):
    data = {"items": items, "total": total, "page": page_no, "pageSize": page_size}
    data.update(extra)
    return ok(data)


def fail(exc: BizError):
    return JSONResponse({"code": exc.code, "message": exc.message, "data": _convert(exc.data)}, status_code=exc.http)


def parse_body(raw: bytes):
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))
