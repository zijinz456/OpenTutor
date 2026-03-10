"""Signal and memory management endpoints for preferences."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from libs.exceptions import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.memory import ConversationMemory
from models.preference import PreferenceSignal
from models.user import User
from routers.preferences_crud import _serialize_memory, _serialize_signal
from schemas.preference import (
    DismissRequest,
    MemoryProfileResponse,
    MemoryUpdateRequest,
    PreferenceSignalResponse,
)
from services.auth.dependency import get_current_user

router = APIRouter()


@router.post("/signals/{signal_id}/dismiss", response_model=PreferenceSignalResponse, summary="Dismiss a signal", description="Mark a preference signal as dismissed with an optional reason.")
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


@router.post("/signals/{signal_id}/restore", response_model=PreferenceSignalResponse, summary="Restore a signal", description="Restore a previously dismissed preference signal to active status.")
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


@router.patch("/memories/{memory_id}", response_model=MemoryProfileResponse, summary="Update a memory", description="Edit a conversation memory summary or category.")
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


@router.post("/memories/{memory_id}/dismiss", response_model=MemoryProfileResponse, summary="Dismiss a memory", description="Mark a conversation memory as dismissed with an optional reason.")
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


@router.post("/memories/{memory_id}/restore", response_model=MemoryProfileResponse, summary="Restore a memory", description="Restore a previously dismissed conversation memory to active status.")
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
