"""Health-check endpoints.

Three tiers:
- /health/live  – process is alive (no I/O, always fast)
- /health/ready – database + LLM reachable (safe for load-balancer readiness probes)
- /health       – full diagnostic (existing behaviour)
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import settings
from services.health import get_health_status, get_liveness, get_readiness

router = APIRouter()


@router.get("/health/live", summary="Liveness probe", description="Lightweight check that the process is alive, no I/O performed.")
async def liveness():
    """Lightweight liveness probe – no I/O."""
    return await get_liveness()


@router.get("/health/ready", summary="Readiness probe", description="Check database connectivity and LLM availability for load balancers.")
async def readiness():
    """Readiness probe – checks DB connectivity and LLM availability."""
    result = await get_readiness()
    status_code = 200 if result["ready"] else 503
    return JSONResponse(content=result, status_code=status_code)


@router.get("/health", summary="Full health check", description="Return full diagnostic status including DB, LLM, and system info.")
async def health():
    return await get_health_status()


@router.get("/features", summary="Feature flags", description="Active experimental feature flags for frontend conditional rendering.")
async def feature_flags():
    return {
        "loom": settings.enable_experimental_loom,
        "lector": settings.enable_experimental_lector,
        "cat_pretest": settings.enable_experimental_cat,
        "browser": settings.enable_experimental_browser,
        "vision": settings.enable_experimental_vision,
        "notion_export": settings.enable_experimental_notion_export,
    }
