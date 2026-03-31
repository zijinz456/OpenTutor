"""Task outcome marking and top-level execution entry point."""

from __future__ import annotations

import logging
import uuid
from sqlalchemy import select

from database import async_session
from libs.datetime_utils import utcnow as _utcnow
from models.agent_task import AgentTask
from services.activity.task_review import (
    attach_task_review_payload,
    build_task_review_payload,
)
from services.activity.task_types import JsonObject, _truncate_summary, infer_approval_status
from services.activity.engine_helpers import (
    TaskCancelledError,
    _refresh_task_checkpoint,
    _refresh_task_policy,
    _task_event,
)
from services.activity.engine_lifecycle import _record_task_audit
from services.provenance import merge_provenance

# Backward-compat re-export (dispatch logic moved to engine_dispatch.py)
from services.activity.engine_dispatch import dispatch_task as _dispatch_task  # noqa: F401

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Mark task outcome
# ------------------------------------------------------------------

async def _mark_task_success(task_id: uuid.UUID, *, result_payload: JsonObject, summary: str | None) -> bool:
    from services.activity.engine_multistep import (
        _queue_auto_repair_follow_up,
        _sync_goal_after_task_success,
    )
    async with async_session() as db:
        result = await db.execute(select(AgentTask).where(AgentTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return False
        now = _utcnow()
        if task.cancel_requested_at is not None:
            task.status = "cancelled"
            task.completed_at = now
            task.error_message = "Cancelled before results were applied."
            task.approval_status = infer_approval_status(
                requires_approval=task.requires_approval, status=task.status, approved_at=task.approved_at,
            )
            _refresh_task_checkpoint(task)
            _task_event(task, "cancelled")
            await _record_task_audit(db, task, action_kind="task_execute_cancelled", outcome="cancelled")
            await db.commit()
            return False
        task.status = "completed"
        goal_update = await _sync_goal_after_task_success(db, task, result_payload)
        stored_result = attach_task_review_payload(
            result_payload,
            build_task_review_payload(task, result_payload, summary, goal_update=goal_update),
        )
        task.summary = _truncate_summary(summary)
        task.result_json = stored_result
        metadata = dict(task.metadata_json or {})
        auto_repair_task_id = await _queue_auto_repair_follow_up(db, task, stored_result)
        if auto_repair_task_id:
            metadata["auto_repair_task_id"] = auto_repair_task_id
            task_review_data = task.result_json.get("task_review") if isinstance(task.result_json, dict) else None
            follow_up_data = task_review_data.get("follow_up") if isinstance(task_review_data, dict) else None
            if isinstance(follow_up_data, dict):
                updated_follow_up = dict(follow_up_data)
                updated_follow_up["auto_queued"] = True
                updated_follow_up["queued_task_id"] = auto_repair_task_id
                updated_task_review = dict(task_review_data)
                updated_task_review["follow_up"] = updated_follow_up
                updated_result = dict(task.result_json)
                updated_result["task_review"] = updated_task_review
                task.result_json = updated_result
        task.metadata_json = metadata
        merged_provenance = merge_provenance(
            metadata.get("provenance") if isinstance(metadata.get("provenance"), dict) else None,
            result_payload.get("provenance") if isinstance(result_payload, dict) else None,
        )
        if merged_provenance:
            metadata["provenance"] = merged_provenance
            task.metadata_json = metadata
            task.provenance_json = merged_provenance
        _refresh_task_checkpoint(task)
        task.approval_status = infer_approval_status(
            requires_approval=task.requires_approval, status=task.status, approved_at=task.approved_at,
        )
        task.error_message = None
        task.completed_at = now
        _task_event(task, "completed")
        await _record_task_audit(
            db, task, action_kind="task_execute_complete", outcome="completed",
            details={"result_keys": sorted(result_payload.keys())[:12]},
        )
        await db.commit()
        return True


async def _mark_task_cancelled(
    task_id: uuid.UUID, *, error_message: str,
    result_payload: JsonObject | None = None, summary: str | None = None,
) -> bool:
    async with async_session() as db:
        result = await db.execute(select(AgentTask).where(AgentTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return False
        now = _utcnow()
        task.status = "cancelled"
        task.error_message = error_message
        task.summary = _truncate_summary(summary) or task.summary
        if result_payload is not None:
            task.result_json = result_payload
            result_provenance = result_payload.get("provenance") if isinstance(result_payload, dict) else None
            task.provenance_json = merge_provenance(task.provenance_json, result_provenance)
        _refresh_task_checkpoint(task)
        task.approval_status = infer_approval_status(
            requires_approval=task.requires_approval, status=task.status, approved_at=task.approved_at,
        )
        task.completed_at = now
        _task_event(task, "cancelled")
        await _record_task_audit(db, task, action_kind="task_execute_cancelled", outcome="cancelled")
        await db.commit()
        return True


async def _mark_task_failure(task_id: uuid.UUID, error_message: str) -> bool:
    async with async_session() as db:
        result = await db.execute(select(AgentTask).where(AgentTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return False
        _refresh_task_policy(task)
        now = _utcnow()
        task.error_message = error_message
        task.completed_at = None
        if task.cancel_requested_at is not None:
            task.status = "cancelled"
            task.completed_at = now
            _task_event(task, "cancelled")
        elif task.attempts < max(task.max_attempts, 1):
            task.status = "queued"
            _task_event(task, "auto_retry_scheduled")
        else:
            task.status = "failed"
            task.completed_at = now
            _task_event(task, "failed")
        _refresh_task_checkpoint(task)
        task.approval_status = infer_approval_status(
            requires_approval=task.requires_approval, status=task.status, approved_at=task.approved_at,
        )
        await _record_task_audit(
            db, task, action_kind="task_execute_failed", outcome=task.status,
            details={"error_message": error_message},
        )
        await db.commit()
        return True


# ------------------------------------------------------------------
# Top-level execute
# ------------------------------------------------------------------

async def execute_task(task_id: uuid.UUID) -> bool:
    async with async_session() as db:
        result = await db.execute(select(AgentTask).where(AgentTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return False
        _refresh_task_policy(task)
        payload = task.input_json or {}

    try:
        result_payload, summary = await _dispatch_task(
            task_id=task_id,
            task_type=task.task_type,
            user_id=task.user_id,
            payload=payload,
        )
    except TaskCancelledError as exc:
        logger.info("Agent task cancelled: %s", task_id)
        return await _mark_task_cancelled(
            task_id, error_message=str(exc),
            result_payload=exc.result_payload, summary=exc.summary,
        )
    except Exception as exc:
        logger.exception("Agent task failed: %s (%s)", task_id, exc)
        return await _mark_task_failure(task_id, str(exc))

    return await _mark_task_success(task_id, result_payload=result_payload, summary=summary)
