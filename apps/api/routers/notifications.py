"""Notifications API — list, read, and dismiss in-app notifications."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.notification import Notification
from models.user import User
from schemas.notification import NotificationResponse, NotificationsListResponse
from services.auth.dependency import get_current_user

router = APIRouter()


def _serialize_notification(n: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=str(n.id),
        title=n.title,
        body=n.body,
        category=n.category,
        read=n.read,
        course_id=str(n.course_id) if n.course_id else None,
        action_url=n.action_url,
        action_label=n.action_label,
        data=n.metadata_json,
        created_at=n.created_at.isoformat() if n.created_at else None,
    )


@router.get("/notifications", response_model=NotificationsListResponse)
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List notifications for the current user, newest first."""
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.read == False)  # noqa: E712
    q = q.order_by(Notification.created_at.desc()).limit(limit)

    result = await db.execute(q)
    notifications = result.scalars().all()

    # Also get unread count
    count_result = await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id,
            Notification.read == False,  # noqa: E712
        )
    )
    unread_count = count_result.scalar() or 0

    return NotificationsListResponse(
        unread_count=unread_count,
        notifications=[_serialize_notification(n) for n in notifications],
    )


@router.post("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark a single notification as read."""
    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user.id)
        .values(read=True)
    )
    await db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark all notifications as read."""
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read == False)  # noqa: E712
        .values(read=True)
    )
    await db.commit()
    return {"ok": True}
