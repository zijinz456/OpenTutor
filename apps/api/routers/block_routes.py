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
