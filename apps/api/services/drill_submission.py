"""Drill submission orchestrator — Phase 16c practice-first pivot (T8).

Wires the runner + persistence + ADHD-safe feedback copy in one
transaction-aware coroutine. The router layer stays dumb (fetch → call →
serialise); all gating, writing, and next-drill lookup happens here.

Flow
----

1. Fetch the target :class:`Drill` or raise :class:`NotFoundError`.
2. Hand ``submitted_code`` + ``hidden_tests`` to
   :func:`services.drill_runner.run_drill` (5s timeout).
3. Persist a :class:`DrillAttempt` row — always, regardless of
   pass/fail — carrying the runner output + duration.
4. Build ADHD-safe feedback copy:

   * pass → short, celebratory, no emoji ("Чисто! Тест пройдено.").
   * fail → short, coaching, no shame ("Ще не все — подивись на
     останній assert і спробуй ще.").

   Per the phase 16 non-negotiable: no "wrong"/"failed"/"incorrect" in
   the copy. ADHD learners drop off fast when the failure mode reads
   punitive.

5. On pass, resolve the course_slug (via Drill → DrillModule →
   DrillCourse) and call :func:`services.drill_selector.select_next_drill`
   so the UI can auto-advance. On fail leave ``next_drill_id`` as
   ``None``.

Error shape
-----------

Follows the Phase 14 freeze service pattern — raise a module-local
dataclass exception (``NotFoundError``) and let the router map it to
HTTP 404. This keeps the service importable by non-FastAPI callers
(seed scripts, tests).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.drill import Drill, DrillAttempt, DrillCourse, DrillModule
from schemas.drills import DrillSubmitResult
from services.drill_runner import run_drill
from services.drill_selector import select_next_drill


_FEEDBACK_PASS = "Чисто! Тест пройдено."
"""Copy shown when the hidden tests pass.

Keep it under a line — long celebration copy reads sarcastic and
slows the next-drill momentum (Phase 16c ADHD principle)."""

_FEEDBACK_FAIL = "Ще не все — подивись на останній assert і спробуй ще."
"""Copy shown on a failing run. Coaching tone, never shame.

The learner already sees the pytest output in ``runner_output``; this
string is the *affect* line above it."""


class NotFoundError(Exception):
    """Raised when the requested drill id does not exist.

    Carried by a dataclass-style exception (module-local) so the router
    can map to HTTP 404 without the service importing FastAPI. Matches
    the Phase 14 :class:`services.freeze.ConflictError` pattern.
    """

    def __init__(self, drill_id: uuid.UUID) -> None:
        super().__init__(f"drill not found: {drill_id}")
        self.drill_id = drill_id


async def _resolve_course_slug(db: AsyncSession, drill: Drill) -> str | None:
    """Walk Drill → DrillModule → DrillCourse to find the parent slug.

    Returns ``None`` only if the join fails (referential anomaly) —
    callers treat that as "no next drill" rather than crashing the
    submit flow; a learner should still get their attempt recorded
    even if downstream navigation breaks.
    """

    stmt = (
        select(DrillCourse.slug)
        .join(DrillModule, DrillModule.course_id == DrillCourse.id)
        .where(DrillModule.id == drill.module_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def submit_drill(
    db: AsyncSession,
    user_id: uuid.UUID,
    drill_id: uuid.UUID,
    submitted_code: str,
) -> DrillSubmitResult:
    """Run a submission end-to-end.

    Args:
        db: Active async SQLAlchemy session. This function commits on
            success — matching the Phase 14 freeze service pattern
            where the service owns durability rather than forcing the
            router to remember it.
        user_id: Learner submitting.
        drill_id: Target drill.
        submitted_code: Learner code (already length-capped upstream
            via :class:`schemas.drills.DrillSubmitRequest`).

    Raises:
        NotFoundError: ``drill_id`` does not match any row. Router
            maps to 404.

    Returns:
        :class:`DrillSubmitResult` with pass/fail, the runner output
        (truncated if large), ADHD-safe ``feedback`` copy, duration,
        and — only on pass — the UUID of the next drill in the
        course (as a string, per schema).
    """

    drill = (
        await db.execute(select(Drill).where(Drill.id == drill_id))
    ).scalar_one_or_none()
    if drill is None:
        raise NotFoundError(drill_id)

    result = await run_drill(submitted_code, drill.hidden_tests, timeout_s=5.0)

    attempt = DrillAttempt(
        user_id=user_id,
        drill_id=drill.id,
        passed=result.passed,
        submitted_code=submitted_code,
        runner_output=result.output,
        duration_ms=result.duration_ms,
    )
    db.add(attempt)

    next_drill_id: str | None = None
    if result.passed:
        course_slug = await _resolve_course_slug(db, drill)
        # Flush the attempt before select_next_drill so the new pass is
        # visible to the selector's query — otherwise the same drill
        # could come back as "next" on the same-request round-trip.
        await db.flush()
        if course_slug is not None:
            nxt = await select_next_drill(db, user_id, course_slug)
            if nxt is not None:
                next_drill_id = str(nxt.id)

    await db.commit()

    return DrillSubmitResult(
        passed=result.passed,
        runner_output=result.output,
        feedback=_FEEDBACK_PASS if result.passed else _FEEDBACK_FAIL,
        duration_ms=result.duration_ms,
        next_drill_id=next_drill_id,
    )


__all__ = [
    "NotFoundError",
    "submit_drill",
]
