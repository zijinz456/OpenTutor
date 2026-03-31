"""LLM runtime configuration and natural-language preference parsing endpoints."""

import json
import logging

from fastapi import APIRouter, Depends
from libs.exceptions import ExternalServiceError, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from schemas.preference import (
    LlmConnectionTestRequest,
    LlmConnectionTestResponse,
    LlmRuntimeConfigResponse,
    LlmRuntimeConfigUpdate,
    NLPreferenceRequest,
    NLPreferenceResult,
    OllamaModelEntry,
)
from services.auth.dependency import get_current_user
from services.llm.local_config import get_llm_runtime_config, get_ollama_models, test_llm_connection

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/runtime/llm", response_model=LlmRuntimeConfigResponse, summary="Get LLM runtime config", description="Read the current local LLM runtime configuration.")
async def get_runtime_llm_config(user: User = Depends(get_current_user)):
    """Read the current local LLM runtime configuration for single-user setups."""
    _ = user
    return get_llm_runtime_config()


@router.put("/runtime/llm", response_model=LlmRuntimeConfigResponse, summary="Update LLM runtime config", description="Persist local LLM runtime config and reload the provider registry.")
async def set_runtime_llm_config(
    body: LlmRuntimeConfigUpdate,
    user: User = Depends(get_current_user),
):
    """Persist local LLM runtime config and reload provider registry."""
    _ = user
    from services.llm.local_config import update_llm_runtime_config
    return update_llm_runtime_config(body.model_dump(exclude_none=True))


@router.post("/runtime/llm/test", response_model=LlmConnectionTestResponse, summary="Test LLM connection", description="Test an LLM provider connection using a draft or saved API key.")
async def test_runtime_llm_config(
    body: LlmConnectionTestRequest,
    user: User = Depends(get_current_user),
):
    """Test a provider connection using a draft or saved API key."""
    _ = user
    try:
        return await test_llm_connection(body.provider, body.model, body.api_key)
    except ValueError as exc:
        raise ValidationError(message=str(exc)) from exc
    except (ConnectionError, OSError, TimeoutError) as exc:
        raise ExternalServiceError(service="LLM", message=str(exc)) from exc


@router.get("/runtime/ollama/models", response_model=list[OllamaModelEntry], summary="List Ollama models", description="Return models available on a running Ollama instance.")
async def list_ollama_models(
    base_url: str | None = None,
    user: User = Depends(get_current_user),
):
    """List models available on a running Ollama instance."""
    _ = user
    try:
        return await get_ollama_models(base_url)
    except (ConnectionError, OSError, TimeoutError, ValueError) as exc:
        raise ExternalServiceError(service="Ollama", message=f"Cannot reach Ollama: {exc}") from exc
    except Exception as exc:
        raise ExternalServiceError(service="Ollama", message=f"Ollama request failed: {exc}") from exc


# ── NL Preference Parsing ──

_NL_PREFERENCE_PROMPT = """\
You are a preference parser for a tutoring app.  Given the user's natural
language request, extract the preference dimension and value.

Available dimensions and valid values:
- note_format: bullet_point | table | mind_map | step_by_step | summary
- detail_level: concise | balanced | detailed
- explanation_style: formal | conversational | socratic | example_heavy
- visual_preference: auto | text_heavy | diagram_heavy | mixed
- language: en | zh | ja | ko | es | fr

Return ONLY a JSON object like {"dimension": "...", "value": "..."}.
If you cannot determine the intent, return {"dimension": null, "value": null}.
"""

_DIRECT_PARSE_SIGNALS: dict[tuple[str, str], tuple[str, ...]] = {
    ("note_format", "bullet_point"): ("bullet", "bullets", "bullet points"),
    ("note_format", "table"): ("table", "tabular"),
    ("note_format", "mind_map"): ("mind map", "mind-map"),
    ("note_format", "step_by_step"): ("step by step", "step-by-step"),
    ("note_format", "summary"): ("summary", "summaries"),
    ("detail_level", "concise"): ("concise", "brief", "short", "shorter", "simplify", "simple"),
    ("detail_level", "balanced"): ("balanced",),
    ("detail_level", "detailed"): ("detailed", "detail", "longer", "more detail", "more details"),
    ("explanation_style", "formal"): ("formal",),
    ("explanation_style", "conversational"): ("conversational", "casual"),
    ("explanation_style", "socratic"): ("socratic",),
    ("explanation_style", "example_heavy"): ("example", "examples"),
    ("visual_preference", "diagram_heavy"): ("diagram", "diagrams", "flowchart", "flowcharts", "visual", "chart", "charts", "graph", "graphs"),
    ("visual_preference", "text_heavy"): ("text", "reading", "written"),
    ("visual_preference", "mixed"): ("mixed", "both"),
    ("language", "en"): ("english", "en"),
    ("language", "zh"): ("chinese", "mandarin", "zh", "中文"),
    ("language", "ja"): ("japanese", "ja", "日本語"),
    ("language", "ko"): ("korean", "ko", "한국어"),
    ("language", "es"): ("spanish", "es", "español"),
    ("language", "fr"): ("french", "fr", "français"),
}

_DIMENSION_CONTEXT_SIGNALS: dict[str, tuple[str, ...]] = {
    "note_format": ("note", "notes", "format", "outline"),
    "detail_level": ("detail", "short", "shorter", "brief", "simple", "detailed", "longer"),
    "explanation_style": ("style", "tone", "voice", "explain", "responses", "example", "examples"),
    "visual_preference": ("visual", "diagram", "diagrams", "flowchart", "chart", "graph", "learner", "text"),
    "language": ("language", "english", "chinese", "japanese", "korean", "spanish", "french", "中文", "日本語", "한국어", "español", "français"),
}


def _is_direct_parse_confident(text: str, dimension: str | None, value: str | None) -> bool:
    if not dimension or not value:
        return False
    normalized = text.casefold().strip()
    value_signals = _DIRECT_PARSE_SIGNALS.get((dimension, value), ())
    context_signals = _DIMENSION_CONTEXT_SIGNALS.get(dimension, ())
    has_value_signal = any(signal in normalized for signal in value_signals)
    has_context_signal = any(signal in normalized for signal in context_signals)
    return has_value_signal and has_context_signal


@router.post("/parse-nl", response_model=NLPreferenceResult, summary="Parse NL preference", description="Parse a natural language preference request into a structured dimension and value.")
async def parse_nl_preference(
    body: NLPreferenceRequest,
    user: User = Depends(get_current_user),
):
    """Parse a natural language preference request using LLM."""
    _ = user
    from services.llm.router import get_registry

    registry = get_registry()
    try:
        client = registry.get("small")
        raw, _usage = await client.extract(_NL_PREFERENCE_PROMPT, body.text)
        # Strip markdown fences if present
        from libs.text_utils import strip_code_fences
        raw = strip_code_fences(raw)
        parsed = json.loads(raw)
        dim = parsed.get("dimension")
        val = parsed.get("value")
        if not _is_direct_parse_confident(body.text, dim, val):
            return NLPreferenceResult()
        label = f"{(dim or '').replace('_', ' ')}: {val}" if dim and val else None
        return NLPreferenceResult(dimension=dim, value=val, label=label)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.debug("NL preference parsing returned unparseable result: %s", e)
        return NLPreferenceResult()
    except (OSError, ConnectionError, TimeoutError, ValueError) as exc:
        logger.exception("NL preference parsing failed")
        return NLPreferenceResult()
