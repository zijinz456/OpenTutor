"""Local LLM configuration persistence for single-user deployments."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values, set_key, unset_key

from config import settings
from services.llm import router as llm_router

LLM_ENV_FIELDS = {
    "llm_provider": "LLM_PROVIDER",
    "llm_model": "LLM_MODEL",
    "llm_required": "LLM_REQUIRED",
    "openai_api_key": "OPENAI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "groq_api_key": "GROQ_API_KEY",
}

PROVIDER_KEY_FIELDS = {
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "deepseek": "deepseek_api_key",
    "openrouter": "openrouter_api_key",
    "gemini": "gemini_api_key",
    "groq": "groq_api_key",
}

LOCAL_PROVIDERS = ("ollama", "lmstudio", "textgenwebui")

LOCAL_BASE_URL_ENV: dict[str, str] = {
    "ollama": "OLLAMA_BASE_URL",
    "vllm": "VLLM_BASE_URL",
    "lmstudio": "LMSTUDIO_BASE_URL",
}

LOCAL_BASE_URL_FIELD: dict[str, str] = {
    "ollama": "ollama_base_url",
    "vllm": "vllm_base_url",
    "lmstudio": "lmstudio_base_url",
}

OPENAI_COMPAT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
}


def _env_path() -> Path:
    configured = os.environ.get("LOCAL_ENV_FILE")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / ".env"


def _mask_secret(secret: str) -> str:
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]}"


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _apply_runtime_setting(field: str, value: Any) -> None:
    setattr(settings, field, value)
    env_name = LLM_ENV_FIELDS[field]
    if isinstance(value, bool):
        os.environ[env_name] = "true" if value else "false"
    elif value:
        os.environ[env_name] = str(value)
    else:
        os.environ.pop(env_name, None)


def _refresh_llm_registry() -> None:
    llm_router._registry = None


def _get_provider_secret(provider: str) -> str:
    field = PROVIDER_KEY_FIELDS.get(provider)
    if not field:
        return ""
    return str(getattr(settings, field, "") or "")


def get_llm_runtime_config() -> dict[str, Any]:
    env_values = dotenv_values(_env_path())
    providers = []
    for provider in (*PROVIDER_KEY_FIELDS.keys(), *LOCAL_PROVIDERS):
        field = PROVIDER_KEY_FIELDS.get(provider)
        raw = str(env_values.get(LLM_ENV_FIELDS[field], "") or getattr(settings, field) or "") if field else ""
        providers.append(
            {
                "provider": provider,
                "has_key": bool(raw),
                "masked_key": _mask_secret(raw) if raw else None,
                "requires_key": provider in PROVIDER_KEY_FIELDS,
            }
        )

    return {
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "llm_required": settings.llm_required,
        "providers": providers,
    }


def update_llm_runtime_config(payload: dict[str, Any]) -> dict[str, Any]:
    env_path = _env_path()
    env_path.touch(exist_ok=True)

    updates: dict[str, Any] = {}
    if "provider" in payload:
        updates["llm_provider"] = str(payload["provider"]).strip().lower()
    if "model" in payload:
        updates["llm_model"] = str(payload["model"]).strip()
    if "llm_required" in payload:
        updates["llm_required"] = _normalize_bool(payload["llm_required"])

    # Handle base_url for local providers
    if "base_url" in payload:
        target_provider = updates.get("llm_provider", settings.llm_provider)
        env_key = LOCAL_BASE_URL_ENV.get(target_provider)
        attr_field = LOCAL_BASE_URL_FIELD.get(target_provider)
        if env_key and attr_field:
            base_url = str(payload["base_url"]).strip().rstrip("/")
            env_path.touch(exist_ok=True)
            set_key(env_path, env_key, base_url, quote_mode="never")
            setattr(settings, attr_field, base_url)
            os.environ[env_key] = base_url

    provider_keys = payload.get("provider_keys") or {}
    for provider, secret in provider_keys.items():
        field = PROVIDER_KEY_FIELDS.get(provider)
        if not field:
            continue
        updates[field] = str(secret).strip()

    for field, value in updates.items():
        env_name = LLM_ENV_FIELDS[field]
        if value == "":
            unset_key(env_path, env_name, quote_mode="never")
        else:
            serialized = "true" if value is True else "false" if value is False else str(value)
            set_key(env_path, env_name, serialized, quote_mode="never")
        _apply_runtime_setting(field, value)

    _refresh_llm_registry()
    return get_llm_runtime_config()


async def test_llm_connection(
    provider: str,
    model: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    provider = provider.strip().lower()
    secret = (api_key or "").strip() or _get_provider_secret(provider)
    if provider not in PROVIDER_KEY_FIELDS and provider not in LOCAL_PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    if provider in PROVIDER_KEY_FIELDS and not secret:
        raise ValueError(f"No API key configured for {provider}")

    selected_model = (model or "").strip() or llm_router._default_model_for_provider(provider, settings.llm_model)

    if provider == "anthropic":
        client = llm_router.AnthropicClient(secret, selected_model)
    elif provider == "ollama":
        client = llm_router.OpenAIClient(
            "ollama",
            selected_model,
            base_url=f"{settings.ollama_base_url}/v1",
            name="ollama",
        )
    elif provider == "lmstudio":
        client = llm_router.OpenAIClient(
            "lm-studio",
            selected_model,
            base_url=settings.lmstudio_base_url,
            name="lmstudio",
        )
    elif provider == "textgenwebui":
        client = llm_router.OpenAIClient(
            "none",
            selected_model,
            base_url=settings.textgenwebui_base_url,
            name="textgenwebui",
        )
    else:
        client = llm_router.OpenAIClient(
            secret,
            selected_model,
            base_url=OPENAI_COMPAT_BASE_URLS.get(provider),
            name=provider,
        )

    response, usage = await client.extract(
        "Return exactly the word OK.",
        "Connection test. Reply with OK only.",
    )
    return {
        "provider": provider,
        "model": selected_model,
        "ok": "OK" in response.upper(),
        "response_preview": response[:80],
        "usage": usage,
    }


logger = logging.getLogger(__name__)


async def get_ollama_models(base_url: str | None = None) -> list[dict[str, Any]]:
    """Fetch available models from a running Ollama instance."""
    url = (base_url or settings.ollama_base_url).rstrip("/")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{url}/api/tags")
        resp.raise_for_status()
        data = resp.json()
    models = data.get("models", [])
    return [
        {
            "name": m.get("name", ""),
            "size": m.get("size", 0),
            "modified_at": m.get("modified_at", ""),
        }
        for m in models
    ]
