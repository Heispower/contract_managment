from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from io import BytesIO

from ..database import get_db
from ..deps import current_user
from ..response import ok
from ..services import importer

router = APIRouter(prefix="/api")


@router.get("/import/{module}/template")
def import_template(module: str, direction: str = "", party_type: str = "", user=Depends(current_user)):
    content, filename = importer.build_template(module, direction, party_type)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.post("/import/{module}/parse")
async def import_parse(
    module: str,
    file: UploadFile = File(...),
    mode: str = Form(""),
    direction: str = Form(""),
    party_type: str = Form(""),
    user=Depends(current_user),
    db=Depends(get_db),
):
    content = await file.read()
    data = importer.parse_upload(
        db,
        user,
        user.session_company_id,
        module,
        content,
        file.filename or "",
        mode,
        direction,
        party_type,
    )
    return ok(data)


@router.post("/import/{module}/execute")
def import_execute(module: str, payload: dict, user=Depends(current_user), db=Depends(get_db)):
    data = importer.execute_upload(db, user, user.session_company_id, module, payload)
    return ok(data)
