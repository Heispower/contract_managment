"""统一列表导出 GET/POST /api/export/{module}。"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from io import BytesIO

from ..database import get_db
from ..deps import current_user
from ..services.list_export import export_file

router = APIRouter(prefix="/api")


def _params(request: Request, payload: dict | None):
    data = {key: value for key, value in request.query_params.items()}
    if payload:
        data.update(payload)
    return data


def _file(module: str, params: dict, user, db):
    content, filename, media = export_file(module, params, user, db)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Download-Name": quote(filename),
    }
    return StreamingResponse(BytesIO(content), media_type=media, headers=headers)


@router.get("/export/{module}")
def export_get(module: str, request: Request, user=Depends(current_user), db=Depends(get_db)):
    return _file(module, _params(request, None), user, db)


@router.post("/export/{module}")
def export_post(module: str, payload: dict, request: Request, user=Depends(current_user), db=Depends(get_db)):
    return _file(module, _params(request, payload or {}), user, db)
