"""Helpers for persistent audit logging."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_log import AuditLog


async def record_audit_log(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None,
    task_id: uuid.UUID | None = None,
    tool_name: str | None = None,
    action_kind: str,
    approval_status: str | None = None,
    outcome: str,
    details_json: dict[str, Any] | None = None,
) -> AuditLog:
    row = AuditLog(
        actor_user_id=actor_user_id,
        task_id=task_id,
        tool_name=tool_name,
        action_kind=action_kind,
        approval_status=approval_status,
        outcome=outcome,
        details_json=details_json,
    )
    db.add(row)
    await db.flush()
    return row
