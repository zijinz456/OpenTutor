"""Course endpoints: aggregate sub-routers for CRUD and sync."""

from fastapi import APIRouter

from routers.courses_crud import router as crud_router
from routers.courses_crud import get_or_create_user, _serialize_content_tree  # noqa: F401 — re-export for dependents
from routers.courses_sync import router as sync_router

router = APIRouter()
router.include_router(crud_router)
router.include_router(sync_router)
