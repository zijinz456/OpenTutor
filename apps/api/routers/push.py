"""Push subscription endpoints — manage Web Push subscriptions for a user."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from libs.exceptions import NotFoundError
from models.push_subscription import PushSubscription
from models.user import User
from schemas.notification import PushSubscriptionCreate, PushSubscriptionDelete
from services.auth.dependency import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/subscribe")
async def subscribe(
    payload: PushSubscriptionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register or update a Web Push subscription for the current user."""
    # Upsert by endpoint — update keys if endpoint already exists
    result = await db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.user_id = user.id
        existing.p256dh_key = payload.p256dh_key
        existing.auth_key = payload.auth_key
        existing.user_agent = payload.user_agent
        existing.is_active = True
        await db.commit()
        logger.info("Push subscription updated for user %s", user.id)
        return {"status": "updated", "subscription_id": str(existing.id)}

    sub = PushSubscription(
        user_id=user.id,
        endpoint=payload.endpoint,
        p256dh_key=payload.p256dh_key,
        auth_key=payload.auth_key,
        user_agent=payload.user_agent,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    logger.info("Push subscription created for user %s", user.id)
    return {"status": "created", "subscription_id": str(sub.id)}


@router.delete("/unsubscribe")
async def unsubscribe(
    payload: PushSubscriptionDelete,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a Web Push subscription by endpoint."""
    result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.endpoint == payload.endpoint,
            PushSubscription.user_id == user.id,
        )
    )
    sub = result.scalar_one_or_none()

    if not sub:
        raise NotFoundError("Subscription")

    sub.is_active = False
    await db.commit()

    logger.info("Push subscription deactivated for user %s", user.id)
    return {"status": "unsubscribed"}


@router.get("/vapid-key")
async def get_vapid_key():
    """Return the server's VAPID public key for browser push registration."""
    if not settings.vapid_public_key:
        raise NotFoundError("VAPID public key")
    return {"public_key": settings.vapid_public_key}
