"""General-purpose key-value store for agent working state.

Replaces ad-hoc metadata_json patterns with structured namespace+key access.
Inspired by AgentFS's KV store pattern.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def kv_get(
    db: AsyncSession,
    user_id: uuid.UUID,
    namespace: str,
    key: str,
    course_id: uuid.UUID | None = None,
) -> dict | None:
    """Fetch a single KV entry. Returns value_json or None."""
    from models.agent_kv import AgentKV

    conditions = [
        AgentKV.user_id == user_id,
        AgentKV.namespace == namespace,
        AgentKV.key == key,
    ]
    if course_id is not None:
        conditions.append(AgentKV.course_id == course_id)
    else:
        conditions.append(AgentKV.course_id.is_(None))

    result = await db.execute(select(AgentKV).where(and_(*conditions)))
    row = result.scalar_one_or_none()
    return row.value_json if row else None


async def kv_set(
    db: AsyncSession,
    user_id: uuid.UUID,
    namespace: str,
    key: str,
    value: Any,
    course_id: uuid.UUID | None = None,
) -> None:
    """Upsert a KV entry. Increments version on update."""
    from models.agent_kv import AgentKV

    conditions = [
        AgentKV.user_id == user_id,
        AgentKV.namespace == namespace,
        AgentKV.key == key,
    ]
    if course_id is not None:
        conditions.append(AgentKV.course_id == course_id)
    else:
        conditions.append(AgentKV.course_id.is_(None))

    result = await db.execute(select(AgentKV).where(and_(*conditions)))
    existing = result.scalar_one_or_none()

    if existing:
        existing.value_json = value
        existing.version += 1
    else:
        entry = AgentKV(
            user_id=user_id,
            course_id=course_id,
            namespace=namespace,
            key=key,
            value_json=value,
        )
        db.add(entry)

    await db.commit()


async def kv_list(
    db: AsyncSession,
    user_id: uuid.UUID,
    namespace: str,
    course_id: uuid.UUID | None = None,
) -> list[dict]:
    """List all KV entries in a namespace."""
    from models.agent_kv import AgentKV

    conditions = [
        AgentKV.user_id == user_id,
        AgentKV.namespace == namespace,
    ]
    if course_id is not None:
        conditions.append(AgentKV.course_id == course_id)

    result = await db.execute(
        select(AgentKV).where(and_(*conditions)).order_by(AgentKV.key)
    )
    rows = result.scalars().all()
    return [{"key": r.key, "value": r.value_json, "version": r.version} for r in rows]


async def kv_delete(
    db: AsyncSession,
    user_id: uuid.UUID,
    namespace: str,
    key: str,
    course_id: uuid.UUID | None = None,
) -> bool:
    """Delete a KV entry. Returns True if something was deleted."""
    from models.agent_kv import AgentKV

    conditions = [
        AgentKV.user_id == user_id,
        AgentKV.namespace == namespace,
        AgentKV.key == key,
    ]
    if course_id is not None:
        conditions.append(AgentKV.course_id == course_id)
    else:
        conditions.append(AgentKV.course_id.is_(None))

    result = await db.execute(select(AgentKV).where(and_(*conditions)))
    existing = result.scalar_one_or_none()

    if existing:
        await db.delete(existing)
        await db.commit()
        return True
    return False
