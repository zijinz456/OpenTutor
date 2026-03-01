"""Preference CRUD and local runtime configuration endpoints."""

import json
import logging
import uuid

from fastapi import APIRouter, Depends
from libs.exceptions import AppError, ValidationError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.preference import PreferenceSignal, UserPreference
from models.user import User
from schemas.preference import PreferenceCreate, PreferenceResponse, ResolvedPreferences
from services.auth.dependency import get_current_user
from services.llm.local_config import get_llm_runtime_config, test_llm_connection, update_llm_runtime_config
from services.preference.engine import resolve_preferences

logger = logging.getLogger(__name__)

router = APIRouter()


class LlmProviderStatus(BaseModel):
    provider: str
    has_key: bool
    masked_key: str | None = None


class LlmRuntimeConfigResponse(BaseModel):
    provider: str
    model: str
    llm_required: bool
    providers: list[LlmProviderStatus]


class LlmRuntimeConfigUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    llm_required: bool | None = None
    provider_keys: dict[str, str] | None = None


class LlmConnectionTestRequest(BaseModel):
    provider: str
    model: str | None = None
    api_key: str | None = None


class LlmConnectionTestResponse(BaseModel):
    provider: str
    model: str
    ok: bool
    response_preview: str
    usage: dict


class PreferenceSignalResponse(BaseModel):
    id: uuid.UUID
    dimension: str
    value: str
    signal_type: str
    course_id: uuid.UUID | None
    context: dict | None
    created_at: str | None


def _normalize_preference_value(dimension: str, value: str) -> str:
    """Normalize legacy/frontend values into canonical Phase 0 values."""
    lowered = value.strip().lower()
    if dimension == "detail_level" and lowered == "moderate":
        return "balanced"
    if dimension == "language":
        if lowered in {"zh-cn", "zh-tw", "zh-hans", "zh-hant"}:
            return "zh"
    if dimension == "explanation_style":
        if lowered in {"analogy", "example_first"}:
            return "example_heavy"
    return value


@router.get("/", response_model=list[PreferenceResponse])
async def list_preferences(
    scope: str | None = None,
    course_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(UserPreference).where(UserPreference.user_id == user.id)
    if scope:
        query = query.where(UserPreference.scope == scope)
    if course_id:
        query = query.where(UserPreference.course_id == course_id)
    result = await db.execute(query.order_by(UserPreference.updated_at.desc()))
    return result.scalars().all()


@router.get("/signals", response_model=list[PreferenceSignalResponse])
async def list_preference_signals(
    course_id: uuid.UUID | None = None,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(PreferenceSignal).where(PreferenceSignal.user_id == user.id)
    if course_id:
        query = query.where(PreferenceSignal.course_id == course_id)
    result = await db.execute(query.order_by(PreferenceSignal.created_at.desc()).limit(limit))
    signals = result.scalars().all()
    return [
        PreferenceSignalResponse(
            id=signal.id,
            dimension=signal.dimension,
            value=signal.value,
            signal_type=signal.signal_type,
            course_id=signal.course_id,
            context=signal.context,
            created_at=signal.created_at.isoformat() if signal.created_at else None,
        )
        for signal in signals
    ]


@router.post("/", response_model=PreferenceResponse, status_code=201)
async def set_preference(body: PreferenceCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    normalized_value = _normalize_preference_value(body.dimension, body.value)

    # Upsert: check if same dimension+scope+course exists
    query = select(UserPreference).where(
        UserPreference.user_id == user.id,
        UserPreference.dimension == body.dimension,
        UserPreference.scope == body.scope,
    )
    if body.course_id:
        query = query.where(UserPreference.course_id == body.course_id)
    else:
        query = query.where(UserPreference.course_id.is_(None))

    result = await db.execute(query)
    existing = result.scalar_one_or_none()

    if existing:
        existing.value = normalized_value
        existing.source = body.source
        existing.confidence = 0.7 if body.source == "onboarding" else 0.5
    else:
        pref = UserPreference(
            user_id=user.id,
            course_id=body.course_id,
            dimension=body.dimension,
            value=normalized_value,
            scope=body.scope,
            source=body.source,
            confidence=0.7 if body.source == "onboarding" else 0.5,
        )
        db.add(pref)
        existing = pref

    await db.commit()
    await db.refresh(existing)
    return existing


@router.get("/resolve", response_model=ResolvedPreferences)
async def resolve(
    course_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resolve all preferences using the 3-layer cascade."""
    return await resolve_preferences(db, user.id, course_id)


@router.get("/runtime/llm", response_model=LlmRuntimeConfigResponse)
async def get_runtime_llm_config(user: User = Depends(get_current_user)):
    """Read the current local LLM runtime configuration for single-user setups."""
    _ = user
    return get_llm_runtime_config()


@router.put("/runtime/llm", response_model=LlmRuntimeConfigResponse)
async def set_runtime_llm_config(
    body: LlmRuntimeConfigUpdate,
    user: User = Depends(get_current_user),
):
    """Persist local LLM runtime config and reload provider registry."""
    _ = user
    return update_llm_runtime_config(body.model_dump(exclude_none=True))


@router.post("/runtime/llm/test", response_model=LlmConnectionTestResponse)
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
    except Exception as exc:
        raise AppError(message=str(exc)) from exc


# ── NL Preference Parsing ──

_NL_PREFERENCE_PROMPT = """\
You are a preference parser for a tutoring app.  Given the user's natural
language request, extract the preference dimension and value.

Available dimensions and valid values:
- note_format: bullet_point | table | mind_map | step_by_step | summary
- detail_level: concise | balanced | detailed
- explanation_style: formal | conversational | socratic | example_heavy
- language: en | zh | ja | ko | es | fr

Return ONLY a JSON object like {"dimension": "...", "value": "..."}.
If you cannot determine the intent, return {"dimension": null, "value": null}.
"""


class NLPreferenceRequest(BaseModel):
    text: str


class NLPreferenceResult(BaseModel):
    dimension: str | None = None
    value: str | None = None
    label: str | None = None


@router.post("/parse-nl", response_model=NLPreferenceResult)
async def parse_nl_preference(
    body: NLPreferenceRequest,
    user: User = Depends(get_current_user),
):
    """Parse a natural language preference request using LLM."""
    _ = user
    from services.llm.router import get_registry

    registry = get_registry()
    try:
        client, model = registry.get_client("small")
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _NL_PREFERENCE_PROMPT},
                {"role": "user", "content": body.text},
            ],
            temperature=0,
            max_tokens=100,
        )
        raw = resp.choices[0].message.content or "{}"
        # Strip markdown fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        parsed = json.loads(raw)
        dim = parsed.get("dimension")
        val = parsed.get("value")
        label = f"{(dim or '').replace('_', ' ')}: {val}" if dim and val else None
        return NLPreferenceResult(dimension=dim, value=val, label=label)
    except Exception as e:
        logger.warning("NL preference parsing failed: %s", e)
        return NLPreferenceResult()
