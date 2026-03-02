"""Learning events API — xAPI-inspired event querying and emission.

Provides endpoints to:
- Query learning events with filters (verb, object_type, course)
- Get aggregated event summaries
- Manually emit events (for frontend-initiated activities)
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth.dependency import get_current_user

router = APIRouter()


# ── Schemas ──


class LearningEventResponse(BaseModel):
    id: str
    verb: str
    object_type: str
    object_id: Optional[str] = None
    score: Optional[float] = None
    success: Optional[bool] = None
    completion: Optional[bool] = None
    duration_seconds: Optional[int] = None
    course_id: Optional[str] = None
    agent_name: Optional[str] = None
    timestamp: datetime


class EventSummaryResponse(BaseModel):
    verb_counts: dict[str, int]
    average_scores: dict[str, dict]
    total_study_seconds: int


class EmitEventRequest(BaseModel):
    verb: str = Field(..., description="Action performed: attempted, answered, completed, reviewed, mastered, created, failed, progressed")
    object_type: str = Field(..., description="Type of learning object: quiz, flashcard, note, exercise, topic, course")
    object_id: Optional[str] = None
    score: Optional[float] = Field(None, ge=0.0, le=1.0)
    success: Optional[bool] = None
    completion: Optional[bool] = None
    duration_seconds: Optional[int] = Field(None, ge=0)
    course_id: Optional[uuid.UUID] = None
    result_json: Optional[dict] = None
    context_json: Optional[dict] = None


# ── Endpoints ──


@router.get("/")
async def list_learning_events(
    course_id: Optional[uuid.UUID] = Query(None),
    verb: Optional[str] = Query(None),
    object_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LearningEventResponse]:
    """List learning events with optional filters."""
    from services.analytics.events import get_learning_events

    events = await get_learning_events(
        db=db,
        user_id=user.id,
        course_id=course_id,
        verb=verb,
        object_type=object_type,
        limit=limit,
        offset=offset,
    )

    return [
        LearningEventResponse(
            id=str(e.id),
            verb=e.verb,
            object_type=e.object_type,
            object_id=e.object_id,
            score=e.score,
            success=e.success,
            completion=e.completion,
            duration_seconds=e.duration_seconds,
            course_id=str(e.course_id) if e.course_id else None,
            agent_name=e.agent_name,
            timestamp=e.timestamp,
        )
        for e in events
    ]


@router.get("/summary")
async def get_event_summary(
    course_id: Optional[uuid.UUID] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventSummaryResponse:
    """Get aggregated learning event summary."""
    from services.analytics.events import get_event_summary as _get_summary

    summary = await _get_summary(db=db, user_id=user.id, course_id=course_id)
    return EventSummaryResponse(**summary)


@router.post("/", status_code=201)
async def emit_event(
    body: EmitEventRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually emit a learning event (e.g., from frontend activities)."""
    from services.analytics.events import emit_learning_event, LearningEventData

    event_id = await emit_learning_event(db, LearningEventData(
        user_id=user.id,
        verb=body.verb,
        object_type=body.object_type,
        object_id=body.object_id,
        score=body.score,
        success=body.success,
        completion=body.completion,
        duration_seconds=body.duration_seconds,
        result_json=body.result_json,
        course_id=body.course_id,
        context_json=body.context_json,
    ))
    await db.commit()

    return {"id": str(event_id), "status": "emitted"}
