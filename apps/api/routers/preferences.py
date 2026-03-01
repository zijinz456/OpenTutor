"""Preference CRUD and local runtime configuration endpoints."""

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from libs.exceptions import AppError, ValidationError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.memory import ConversationMemory
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
    dismissed_at: str | None = None
    dismissal_reason: str | None = None


class PreferenceUpdateRequest(BaseModel):
    value: str | None = None
    scope: str | None = None
    source: str | None = None
    scene_type: str | None = None


class DismissRequest(BaseModel):
    reason: str | None = None


class MemoryProfileResponse(BaseModel):
    id: uuid.UUID
    summary: str
    memory_type: str
    category: str | None
    importance: float
    access_count: int
    source_message: str | None
    metadata_json: dict | None
    created_at: str | None
    updated_at: str | None
    dismissed_at: str | None = None
    dismissal_reason: str | None = None


class LearningProfileSummary(BaseModel):
    strength_areas: list[str]
    weak_areas: list[str]
    recurring_errors: list[str]
    inferred_habits: list[str]


class LearningProfileResponse(BaseModel):
    preferences: list[PreferenceResponse]
    dismissed_preferences: list[PreferenceResponse]
    signals: list[PreferenceSignalResponse]
    dismissed_signals: list[PreferenceSignalResponse]
    memories: list[MemoryProfileResponse]
    dismissed_memories: list[MemoryProfileResponse]
    summary: LearningProfileSummary


def _serialize_signal(signal: PreferenceSignal) -> PreferenceSignalResponse:
    return PreferenceSignalResponse(
        id=signal.id,
        dimension=signal.dimension,
        value=signal.value,
        signal_type=signal.signal_type,
        course_id=signal.course_id,
        context=signal.context,
        created_at=signal.created_at.isoformat() if signal.created_at else None,
        dismissed_at=signal.dismissed_at.isoformat() if signal.dismissed_at else None,
        dismissal_reason=signal.dismissal_reason,
    )


def _serialize_memory(memory: ConversationMemory) -> MemoryProfileResponse:
    return MemoryProfileResponse(
        id=memory.id,
        summary=memory.summary,
        memory_type=memory.memory_type,
        category=memory.category,
        importance=memory.importance,
        access_count=memory.access_count,
        source_message=memory.source_message,
        metadata_json=memory.metadata_json,
        created_at=memory.created_at.isoformat() if memory.created_at else None,
        updated_at=memory.updated_at.isoformat() if memory.updated_at else None,
        dismissed_at=memory.dismissed_at.isoformat() if memory.dismissed_at else None,
        dismissal_reason=memory.dismissal_reason,
    )


def build_learning_profile_summary(memories: list[ConversationMemory]) -> LearningProfileSummary:
    strengths = [mem.summary for mem in memories if mem.memory_type in {"skill", "knowledge"}][:5]
    weak_areas = [mem.summary for mem in memories if mem.memory_type == "error"][:5]
    recurring_errors = [mem.summary for mem in memories if mem.memory_type == "error"][:5]
    inferred_habits = [mem.summary for mem in memories if mem.memory_type in {"profile", "preference", "episode"}][:5]
    return LearningProfileSummary(
        strength_areas=strengths,
        weak_areas=weak_areas,
        recurring_errors=recurring_errors,
        inferred_habits=inferred_habits,
    )


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
    include_dismissed: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(UserPreference).where(UserPreference.user_id == user.id)
    if scope:
        query = query.where(UserPreference.scope == scope)
    if course_id:
        query = query.where(UserPreference.course_id == course_id)
    if not include_dismissed:
        query = query.where(UserPreference.dismissed_at.is_(None))
    result = await db.execute(query.order_by(UserPreference.updated_at.desc()))
    return result.scalars().all()


@router.get("/signals", response_model=list[PreferenceSignalResponse])
async def list_preference_signals(
    course_id: uuid.UUID | None = None,
    limit: int = 20,
    include_dismissed: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(PreferenceSignal).where(PreferenceSignal.user_id == user.id)
    if course_id:
        query = query.where(PreferenceSignal.course_id == course_id)
    if not include_dismissed:
        query = query.where(PreferenceSignal.dismissed_at.is_(None))
    result = await db.execute(query.order_by(PreferenceSignal.created_at.desc()).limit(limit))
    signals = result.scalars().all()
    return [_serialize_signal(signal) for signal in signals]


@router.get("/profile", response_model=LearningProfileResponse)
async def get_learning_profile(
    course_id: uuid.UUID | None = None,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pref_query = select(UserPreference).where(UserPreference.user_id == user.id)
    signal_query = select(PreferenceSignal).where(PreferenceSignal.user_id == user.id)
    memory_query = select(ConversationMemory).where(ConversationMemory.user_id == user.id)

    if course_id:
        pref_query = pref_query.where(
            (UserPreference.course_id == course_id) | UserPreference.course_id.is_(None)
        )
        signal_query = signal_query.where(
            (PreferenceSignal.course_id == course_id) | PreferenceSignal.course_id.is_(None)
        )
        memory_query = memory_query.where(
            (ConversationMemory.course_id == course_id) | ConversationMemory.course_id.is_(None)
        )

    pref_result = await db.execute(pref_query.order_by(UserPreference.updated_at.desc()).limit(limit * 2))
    signal_result = await db.execute(signal_query.order_by(PreferenceSignal.created_at.desc()).limit(limit * 2))
    memory_result = await db.execute(memory_query.order_by(ConversationMemory.updated_at.desc()).limit(limit * 2))

    preferences = list(pref_result.scalars().all())
    signals = list(signal_result.scalars().all())
    memories = list(memory_result.scalars().all())

    active_preferences = [pref for pref in preferences if pref.dismissed_at is None][:limit]
    dismissed_preferences = [pref for pref in preferences if pref.dismissed_at is not None][:limit]
    active_signals = [signal for signal in signals if signal.dismissed_at is None][:limit]
    dismissed_signals = [signal for signal in signals if signal.dismissed_at is not None][:limit]
    active_memories = [memory for memory in memories if memory.dismissed_at is None][:limit]
    dismissed_memories = [memory for memory in memories if memory.dismissed_at is not None][:limit]

    return LearningProfileResponse(
        preferences=[PreferenceResponse.model_validate(pref) for pref in active_preferences],
        dismissed_preferences=[PreferenceResponse.model_validate(pref) for pref in dismissed_preferences],
        signals=[_serialize_signal(signal) for signal in active_signals],
        dismissed_signals=[_serialize_signal(signal) for signal in dismissed_signals],
        memories=[_serialize_memory(memory) for memory in active_memories],
        dismissed_memories=[_serialize_memory(memory) for memory in dismissed_memories],
        summary=build_learning_profile_summary(active_memories),
    )


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
        existing.dismissed_at = None
        existing.dismissal_reason = None
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


@router.patch("/{preference_id}", response_model=PreferenceResponse)
async def update_preference(
    preference_id: uuid.UUID,
    body: PreferenceUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserPreference).where(UserPreference.id == preference_id, UserPreference.user_id == user.id)
    )
    pref = result.scalar_one_or_none()
    if not pref:
        raise ValidationError(message="Preference not found")

    payload = body.model_dump(exclude_unset=True)
    if "value" in payload and payload["value"] is not None:
        pref.value = _normalize_preference_value(pref.dimension, payload["value"])
        pref.dismissed_at = None
        pref.dismissal_reason = None
    if "scope" in payload and payload["scope"] is not None:
        pref.scope = payload["scope"]
    if "source" in payload and payload["source"] is not None:
        pref.source = payload["source"]
    if "scene_type" in payload:
        pref.scene_type = payload["scene_type"]

    await db.commit()
    await db.refresh(pref)
    return pref


@router.post("/{preference_id}/dismiss", response_model=PreferenceResponse)
async def dismiss_preference(
    preference_id: uuid.UUID,
    body: DismissRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserPreference).where(UserPreference.id == preference_id, UserPreference.user_id == user.id)
    )
    pref = result.scalar_one_or_none()
    if not pref:
        raise ValidationError(message="Preference not found")
    pref.dismissed_at = datetime.now(timezone.utc)
    pref.dismissal_reason = body.reason
    await db.commit()
    await db.refresh(pref)
    return pref


@router.post("/{preference_id}/restore", response_model=PreferenceResponse)
async def restore_preference(
    preference_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserPreference).where(UserPreference.id == preference_id, UserPreference.user_id == user.id)
    )
    pref = result.scalar_one_or_none()
    if not pref:
        raise ValidationError(message="Preference not found")
    pref.dismissed_at = None
    pref.dismissal_reason = None
    await db.commit()
    await db.refresh(pref)
    return pref


@router.post("/signals/{signal_id}/dismiss", response_model=PreferenceSignalResponse)
async def dismiss_preference_signal(
    signal_id: uuid.UUID,
    body: DismissRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PreferenceSignal).where(PreferenceSignal.id == signal_id, PreferenceSignal.user_id == user.id)
    )
    signal = result.scalar_one_or_none()
    if not signal:
        raise ValidationError(message="Preference signal not found")
    signal.dismissed_at = datetime.now(timezone.utc)
    signal.dismissal_reason = body.reason
    await db.commit()
    await db.refresh(signal)
    return _serialize_signal(signal)


@router.post("/signals/{signal_id}/restore", response_model=PreferenceSignalResponse)
async def restore_preference_signal(
    signal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PreferenceSignal).where(PreferenceSignal.id == signal_id, PreferenceSignal.user_id == user.id)
    )
    signal = result.scalar_one_or_none()
    if not signal:
        raise ValidationError(message="Preference signal not found")
    signal.dismissed_at = None
    signal.dismissal_reason = None
    await db.commit()
    await db.refresh(signal)
    return _serialize_signal(signal)


class MemoryUpdateRequest(BaseModel):
    summary: str | None = None
    category: str | None = None


@router.patch("/memories/{memory_id}", response_model=MemoryProfileResponse)
async def update_memory(
    memory_id: uuid.UUID,
    body: MemoryUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ConversationMemory).where(ConversationMemory.id == memory_id, ConversationMemory.user_id == user.id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise ValidationError(message="Memory not found")

    payload = body.model_dump(exclude_unset=True)
    if "summary" in payload and payload["summary"] is not None:
        memory.summary = payload["summary"].strip()
        memory.dismissed_at = None
        memory.dismissal_reason = None
    if "category" in payload:
        memory.category = payload["category"]
    await db.commit()
    await db.refresh(memory)
    return _serialize_memory(memory)


@router.post("/memories/{memory_id}/dismiss", response_model=MemoryProfileResponse)
async def dismiss_memory(
    memory_id: uuid.UUID,
    body: DismissRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ConversationMemory).where(ConversationMemory.id == memory_id, ConversationMemory.user_id == user.id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise ValidationError(message="Memory not found")
    memory.dismissed_at = datetime.now(timezone.utc)
    memory.dismissal_reason = body.reason
    await db.commit()
    await db.refresh(memory)
    return _serialize_memory(memory)


@router.post("/memories/{memory_id}/restore", response_model=MemoryProfileResponse)
async def restore_memory(
    memory_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ConversationMemory).where(ConversationMemory.id == memory_id, ConversationMemory.user_id == user.id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise ValidationError(message="Memory not found")
    memory.dismissed_at = None
    memory.dismissal_reason = None
    await db.commit()
    await db.refresh(memory)
    return _serialize_memory(memory)


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
