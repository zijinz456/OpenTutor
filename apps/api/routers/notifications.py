"""Notification endpoints — polling + SSE for proactive reminders."""

import uuid
import logging

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from services.scheduler.engine import get_notifications, mark_notification_read

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


@router.get("/", response_model=list[NotificationOut])
async def list_notifications(
    user_id: uuid.UUID = Query(...),
    unread_only: bool = Query(True),
):
    """List notifications for a user."""
    notifications = get_notifications(user_id, unread_only)
    logger.info(
        "Notifications fetched: user_id=%s unread_only=%s count=%d",
        user_id,
        unread_only,
        len(notifications),
    )
    return notifications


@router.post("/{notification_id}/read")
async def read_notification(notification_id: str):
    """Mark a notification as read."""
    updated = mark_notification_read(notification_id)
    if not updated:
        logger.warning("Notification not found: id=%s", notification_id)
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "ok"}
