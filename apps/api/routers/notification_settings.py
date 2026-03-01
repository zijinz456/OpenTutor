"""Notification settings endpoints — manage per-user notification preferences."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from schemas.notification import NotificationSettingsResponse, NotificationSettingsUpdate
from services.auth.dependency import get_current_user
from services.notification.dispatcher import get_or_create_settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/settings", response_model=NotificationSettingsResponse)
async def get_notification_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get notification settings for the current user (creates defaults if none exist)."""
    settings = await get_or_create_settings(user.id, db)
    await db.commit()
    return settings


@router.put("/settings", response_model=NotificationSettingsResponse)
async def update_notification_settings(
    payload: NotificationSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update notification preferences for the current user."""
    settings = await get_or_create_settings(user.id, db)

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(settings, field, value)

    await db.commit()
    await db.refresh(settings)

    logger.info("Notification settings updated for user %s: %s", user.id, list(update_data.keys()))
    return settings
