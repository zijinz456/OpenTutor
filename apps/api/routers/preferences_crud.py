"""Preference CRUD endpoints: list, create, update, dismiss, restore."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from libs.exceptions import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.memory import ConversationMemory
from models.preference import PreferenceSignal, UserPreference
from models.user import User
from schemas.preference import (
    DismissRequest,
    LearningProfileResponse,
    LearningProfileSummary,
    MemoryProfileResponse,
    PreferenceCreate,
    PreferenceResponse,
    PreferenceSignalResponse,
    PreferenceUpdateRequest,
    ResolvedPreferences,
)
from services.auth.dependency import get_current_user
from services.preference.engine import resolve_preferences

router = APIRouter()


def _serialize_signal(signal: PreferenceSignal) -> PreferenceSignalResponse:
    return PreferenceSignalResponse(
        id=signal.id,
        dimension=signal.dimension,
        value=signal.value,
        signal_type=signal.signal_type,
        course_id=signal.course_id,
        context=signal.context,
        created_at=signal.created_at,
        dismissed_at=signal.dismissed_at,
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
        created_at=memory.created_at,
        updated_at=memory.updated_at,
        dismissed_at=memory.dismissed_at,
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


@router.get("/", response_model=list[PreferenceResponse], summary="List user preferences", description="Return preferences filtered by scope, course, and dismissal status.")
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


@router.get("/signals", response_model=list[PreferenceSignalResponse], summary="List preference signals", description="Return AI-detected preference signals for the current user.")
async def list_preference_signals(
    course_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
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


@router.get("/profile", response_model=LearningProfileResponse, summary="Get learning profile", description="Return the full learning profile including preferences, signals, and memories.")
async def get_learning_profile(
    course_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
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


@router.post("/", response_model=PreferenceResponse, status_code=201, summary="Set a preference", description="Create or update a user preference with dimension, value, and scope.")
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


@router.patch("/{preference_id}", response_model=PreferenceResponse, summary="Update a preference", description="Partially update a preference value, scope, or source.")
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


@router.post("/{preference_id}/dismiss", response_model=PreferenceResponse, summary="Dismiss a preference", description="Mark a preference as dismissed with an optional reason.")
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


@router.post("/{preference_id}/restore", response_model=PreferenceResponse, summary="Restore a preference", description="Restore a previously dismissed preference to active status.")
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


@router.get("/resolve", response_model=ResolvedPreferences, summary="Resolve preferences", description="Resolve all preferences using the 3-layer cascade for a user and optional course.")
async def resolve(
    course_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resolve all preferences using the 3-layer cascade."""
    return await resolve_preferences(db, user.id, course_id)
