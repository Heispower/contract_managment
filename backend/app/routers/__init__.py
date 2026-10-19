from fastapi import APIRouter

from .auth_api import router as auth_router
from .biz_api import router as biz_router
from .customs_api import router as customs_router
from .export_api import router as export_router
from .import_api import router as import_router
from .misc_api import router as misc_router
from .number_api import router as number_router

api = APIRouter()
api.include_router(auth_router)
api.include_router(biz_router)
api.include_router(customs_router)
api.include_router(export_router)
api.include_router(import_router)
api.include_router(misc_router)
api.include_router(number_router)
