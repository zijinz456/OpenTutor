"""Health-check endpoints."""

from fastapi import APIRouter

from services.health import get_health_status

router = APIRouter()


@router.get("/health")
async def health():
    return await get_health_status()
