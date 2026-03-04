"""Notification endpoints — DB-backed polling + SSE for proactive reminders."""

import asyncio
import uuid
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from database import get_db
from libs.exceptions import NotFoundError
from models.notification import Notification
from models.user import User
from services.auth.dependency import get_current_user
from utils.serializers import serialize_model

router = APIRouter()
logger = logging.getLogger(__name__)


class NotificationOut(BaseModel):
    id: str
    user_id: str
    title: str
    body: str
    category: str
    created_at: str
    read: bool
    priority: str | None = None
    action_url: str | None = None
    action_label: str | None = None
    metadata_json: dict | None = None


@router.get("/", response_model=list[NotificationOut])
async def list_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unread_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
):
    """List notifications for a user."""
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read == False)
    query = query.order_by(Notification.created_at.desc()).limit(limit)

    result = await db.execute(query)
    rows = result.scalars().all()
    fields = [
        "id", "user_id", "title", "body", "category", "created_at", "read",
        "priority", "action_url", "action_label", "metadata_json",
    ]
    return [NotificationOut(**serialize_model(n, fields)) for n in rows]


@router.post("/{notification_id}/read")
async def read_notification(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a notification as read."""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise NotFoundError("Notification", notification_id)
    notif.read = True
    await db.commit()
    return {"status": "ok"}


@router.get("/stream")
async def notification_stream(user: User = Depends(get_current_user)):
    """SSE endpoint for real-time notification push."""
    from services.notification.channels.sse import subscribe_sse, unsubscribe_sse

    queue = subscribe_sse(user.id)

    async def event_generator():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {"event": "notification", "data": payload}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe_sse(user.id, queue)

    return EventSourceResponse(event_generator())
