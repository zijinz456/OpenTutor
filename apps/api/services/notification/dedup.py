"""Notification deduplication utilities.

Prevents duplicate notifications by generating deterministic dedup keys
based on user, category, batch context, and date.
"""

import hashlib
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification


def compute_dedup_key(
    user_id: uuid.UUID,
    category: str,
    batch_key: str | None,
    target_date: date | None = None,
) -> str:
    """Generate a deterministic deduplication key.

    Format: sha256(user_id:category:batch_key:date)[:40]
    If batch_key is None, only user_id + category + date are used.
    """
    if target_date is None:
        target_date = date.today()

    parts = [str(user_id), category]
    if batch_key:
        parts.append(batch_key)
    parts.append(target_date.isoformat())

    raw = ":".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


async def check_dedup(dedup_key: str, db: AsyncSession) -> bool:
    """Check if a notification with this dedup key already exists.

    Returns True if a duplicate exists (i.e., should be skipped).
    """
    result = await db.execute(
        select(Notification.id).where(Notification.dedup_key == dedup_key).limit(1)
    )
    return result.scalar_one_or_none() is not None
