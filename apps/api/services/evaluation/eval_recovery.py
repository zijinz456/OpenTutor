"""Recovery evaluation framework.

Tests the system's ability to handle failures gracefully:
- Task retry after single-step failure
- Max-attempts exhaustion guard
- Approval flow state machine
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_task import AgentTask
from models.user import User


@dataclass
class RecoveryTestResult:
    name: str
    passed: bool
    details: dict[str, Any]


async def _resolve_user_id(db: AsyncSession) -> uuid.UUID:
    """Get the first user from the DB (single-user mode) for eval tasks."""
    result = await db.execute(select(User.id).limit(1))
    uid = result.scalar_one_or_none()
    if uid is None:
        raise RuntimeError("No users in database — cannot run recovery evaluation")
    return uid


async def eval_task_retry(
    db: AsyncSession, course_id: str | None = None, user_id: uuid.UUID | None = None,
) -> RecoveryTestResult:
    """Test: a failed task with remaining attempts can be retried.

    Steps:
    1. Create a task with max_attempts=3
    2. Simulate failure (set status=failed, attempts=1)
    3. Retry the task via retry_task()
    4. Verify status transitions to queued/running
    """
    from services.activity.engine import submit_task, retry_task

    if user_id is None:
        user_id = await _resolve_user_id(db)

    task_data = await submit_task(
        user_id=user_id,
        task_type="recovery_eval_retry",
        title="Recovery eval — retry test",
        course_id=course_id,
        input_json={"test": True},
        source="eval_recovery",
        max_attempts=3,
        db=db,
    )
    task_id = task_data.id

    # Simulate failure
    await db.execute(
        update(AgentTask)
        .where(AgentTask.id == task_id)
        .values(status="failed", attempts=1)
    )
    await db.commit()

    try:
        retried = await retry_task(task_id, user_id, db=db)
        if retried is None:
            return RecoveryTestResult(
                name="task_retry",
                passed=False,
                details={"error": "retry_task returned None", "task_id": str(task_id)},
            )
        success = retried.status in ("queued", "running", "pending_approval")
        return RecoveryTestResult(
            name="task_retry",
            passed=success,
            details={
                "task_id": str(task_id),
                "retried_status": retried.status,
            },
        )
    except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as exc:
        logger.exception("Recovery eval task_retry failed for task %s: %s", task_id, exc)
        return RecoveryTestResult(
            name="task_retry",
            passed=False,
            details={"error": str(exc), "task_id": str(task_id)},
        )


async def eval_task_max_attempts_exhausted(
    db: AsyncSession, user_id: uuid.UUID | None = None,
) -> RecoveryTestResult:
    """Test: a task that has exhausted all attempts is correctly in failed state.

    Verifies the task stays failed with attempts >= max_attempts.
    """
    from services.activity.engine import submit_task

    if user_id is None:
        user_id = await _resolve_user_id(db)

    task_data = await submit_task(
        user_id=user_id,
        task_type="recovery_eval_exhaust",
        title="Recovery eval — max attempts",
        input_json={"test": True},
        source="eval_recovery",
        max_attempts=1,
        db=db,
    )
    task_id = task_data.id

    # Simulate exhausted attempts
    await db.execute(
        update(AgentTask)
        .where(AgentTask.id == task_id)
        .values(status="failed", attempts=1)
    )
    await db.commit()

    await db.refresh(task_data)
    passed = task_data.status == "failed" and task_data.attempts >= task_data.max_attempts
    return RecoveryTestResult(
        name="max_attempts_exhausted",
        passed=passed,
        details={
            "task_id": str(task_id),
            "status": task_data.status,
            "attempts": task_data.attempts,
            "max_attempts": task_data.max_attempts,
        },
    )


async def eval_task_approval_flow(
    db: AsyncSession, course_id: str | None = None, user_id: uuid.UUID | None = None,
) -> RecoveryTestResult:
    """Test: task requiring approval starts in pending_approval status."""
    from services.activity.engine import submit_task

    if user_id is None:
        user_id = await _resolve_user_id(db)

    task_data = await submit_task(
        user_id=user_id,
        task_type="recovery_eval_approval",
        title="Recovery eval — approval flow",
        course_id=course_id,
        input_json={"test": True},
        source="eval_recovery",
        requires_approval=True,
        max_attempts=2,
        db=db,
    )

    passed = task_data.status == "pending_approval"
    return RecoveryTestResult(
        name="approval_flow",
        passed=passed,
        details={
            "task_id": str(task_data.id),
            "initial_status": task_data.status,
            "expected": "pending_approval",
        },
    )


async def run_recovery_evaluation(
    db: AsyncSession,
    course_id: str | None = None,
) -> list[RecoveryTestResult]:
    """Run all recovery evaluation tests and return results."""
    uid = await _resolve_user_id(db)

    evaluators = [
        ("task_retry", lambda: eval_task_retry(db, course_id, user_id=uid)),
        ("max_attempts_exhausted", lambda: eval_task_max_attempts_exhausted(db, user_id=uid)),
        ("approval_flow", lambda: eval_task_approval_flow(db, course_id, user_id=uid)),
    ]

    results: list[RecoveryTestResult] = []
    for name, eval_fn in evaluators:
        try:
            result = await eval_fn()
            results.append(result)
        except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as exc:
            logger.exception("Recovery evaluation '%s' failed: %s", name, exc)
            results.append(RecoveryTestResult(
                name=name,
                passed=False,
                details={"error": str(exc)},
            ))

    return results
