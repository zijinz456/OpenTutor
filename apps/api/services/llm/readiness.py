"""LLM readiness helpers for production-facing AI features."""

from __future__ import annotations

from typing import Any

from config import settings
from libs.exceptions import LLMUnavailableError
from services.llm.router import get_registry


def _status_message(feature_name: str, status: str, primary_name: str | None) -> str:
    if status == "configuration_required":
        return (
            f"{feature_name} is unavailable because no LLM provider is configured "
            "and LLM_REQUIRED is enabled."
        )
    if status == "mock_fallback":
        return (
            f"{feature_name} requires a real LLM provider. Configure Ollama or a "
            "cloud LLM provider before using this feature."
        )
    if status == "degraded":
        provider_label = primary_name or "configured"
        return (
            f"{feature_name} is temporarily unavailable because the primary LLM "
            f"provider '{provider_label}' is unhealthy."
        )
    return f"{feature_name} is unavailable because the LLM runtime is not ready."


async def get_llm_runtime_status(*, probe_if_needed: bool = True) -> dict[str, Any]:
    """Return current LLM runtime readiness without involving database state."""
    registry = get_registry()
    probe_details = registry.provider_health_cached
    if probe_details:
        provider_health = {name: details["healthy"] for name, details in probe_details.items()}
    elif probe_if_needed:
        provider_health = await registry.ping_all()
        probe_details = {
            name: {"healthy": healthy, "status": "ok" if healthy else "unhealthy", "error": None}
            for name, healthy in provider_health.items()
        }
    else:
        provider_health = registry.provider_health
        probe_details = {
            name: {"healthy": healthy, "status": "ok" if healthy else "unhealthy", "error": None}
            for name, healthy in provider_health.items()
        }

    if not registry.available_providers:
        status = "configuration_required" if settings.llm_required else "mock_fallback"
    elif registry.primary_name == "mock":
        status = "mock_fallback"
    elif registry.primary_name and not provider_health.get(registry.primary_name, True):
        status = "degraded"
    else:
        status = "ready"

    return {
        "status": status,
        "primary_name": registry.primary_name,
        "available_providers": registry.available_providers,
        "provider_health": provider_health,
        "provider_details": probe_details,
        "llm_required": settings.llm_required,
    }


async def ensure_llm_ready(feature_name: str, *, allow_degraded: bool = False) -> None:
    """Fail fast when a user-facing AI feature would run against mock or unhealthy LLMs."""
    runtime = await get_llm_runtime_status()
    status = runtime["status"]
    if status == "ready" or (allow_degraded and status == "degraded"):
        return
    raise LLMUnavailableError(_status_message(feature_name, status, runtime["primary_name"]))
