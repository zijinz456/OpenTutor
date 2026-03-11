"""Block interaction event endpoints.

Collects block engagement/interaction events from the frontend
and exposes computed preference scores.
"""

import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

logger = logging.getLogger(__name__)

router = APIRouter()


class BlockEvent(BaseModel):
    block_type: str
    event_type: str  # "view", "approve", "dismiss", "manual_add", "manual_remove"
    duration_ms: int = 0
    course_id: str


class BlockEventsRequest(BaseModel):
    events: list[BlockEvent] = Field(default_factory=list, max_length=50)


@router.post("/events", summary="Record block interaction events")
async def record_events(
    body: BlockEventsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept a batch of block interaction events from the frontend."""
    from services.block_decision.preference import record_block_event

    recorded = 0
    for event in body.events:
        try:
            course_uuid = uuid.UUID(event.course_id)
        except ValueError:
            continue
        await record_block_event(
            db=db,
            user_id=user.id,
            course_id=course_uuid,
            event_type=event.event_type,
            block_type=event.block_type,
            metadata={"duration_ms": event.duration_ms} if event.duration_ms else None,
        )
        recorded += 1

    await db.commit()
    return {"recorded": recorded}


class InterventionFeedback(BaseModel):
    intervention_id: str
    feedback: str  # "helpful" | "not_helpful"


@router.post("/intervention-feedback", summary="Record user feedback on an intervention")
async def record_intervention_feedback(
    body: InterventionFeedback,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept user feedback (thumbs up/down) on a block intervention."""
    from sqlalchemy import select
    from models.intervention_outcome import InterventionOutcome

    if body.feedback not in ("helpful", "not_helpful"):
        return {"error": "feedback must be 'helpful' or 'not_helpful'"}

    try:
        outcome_id = uuid.UUID(body.intervention_id)
    except ValueError:
        return {"error": "invalid intervention_id"}

    result = await db.execute(
        select(InterventionOutcome).where(
            InterventionOutcome.id == outcome_id,
            InterventionOutcome.user_id == user.id,
        )
    )
    outcome = result.scalar_one_or_none()
    if not outcome:
        return {"error": "intervention not found"}

    outcome.user_feedback = body.feedback
    await db.commit()
    return {"ok": True}


@router.get("/preferences", summary="Get block preference scores")
async def get_preferences(
    course_id: uuid.UUID = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return computed block preference scores for a course."""
    await get_course_or_404(db, course_id, user_id=user.id)
    from services.block_decision.preference import compute_block_preferences

    scores = await compute_block_preferences(db, user.id, course_id)
    return {"preferences": scores}
