"""Block interaction event endpoints.

Collects block engagement/interaction events from the frontend; the
block-decision engine reads the resulting preference scores each turn.
"""

import uuid
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth.dependency import get_current_user

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
