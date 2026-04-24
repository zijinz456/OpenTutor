"""Next-drill selector — Phase 16c practice-first pivot (T7).

Picks the next drill for a learner inside a given course. MVP rule
(deliberately dumb & deterministic):

1. Walk modules in ``order_index`` ascending.
2. Inside each module, walk drills in ``order_index`` ascending.
3. Return the **first drill** for which the user has NOT yet logged a
   ``DrillAttempt`` with ``passed=True``.
4. Return ``None`` when every drill has already been passed — the
   caller maps that to a "course complete" UI state.

No XP / FSRS / recency weighting in the MVP. The richer adaptive
selection (difficulty review, skill-tag coverage) is downstream
(critic C5 — scheduled for T21).

Query shape
-----------

Single round-trip via a LEFT JOIN on ``drill_attempts`` filtered to the
caller's user_id + ``passed=True`` — we then take the lowest-ordered
drill where the join produced NULL (i.e. no passing attempt).

A two-query variant (fetch all drills, fetch passed ids, filter in
Python) is functionally equivalent at this scale (a drill course has
O(100) drills), but a single SQL query also gives us a stable sort
order at the DB without pulling rows we won't use.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.drill import Drill, DrillAttempt, DrillCourse, DrillModule


async def select_next_drill(
    db: AsyncSession, user_id: uuid.UUID, course_slug: str
) -> Drill | None:
    """Return the next unpassed drill for ``user_id`` inside ``course_slug``.

    Args:
        db: Active async SQLAlchemy session.
        user_id: Learner whose attempt history we check.
        course_slug: Slug of the :class:`DrillCourse` to scan. A
            non-existent course returns ``None`` (same signal as a
            completed course — the router can disambiguate via a
            prior existence check if it cares).

    Returns:
        The first :class:`Drill` (by module order, then drill order)
        with no ``passed=True`` attempt by this user. ``None`` when
        the course doesn't exist, contains no drills, or is fully
        complete.
    """

    course = (
        await db.execute(select(DrillCourse).where(DrillCourse.slug == course_slug))
    ).scalar_one_or_none()
    if course is None:
        return None

    # Fetch passed drill_ids first. This is a small set (one row per
    # distinct drill the user has completed) so pulling it into memory
    # keeps the main query plain and the JOIN unnecessary.
    passed_rows = await db.execute(
        select(DrillAttempt.drill_id)
        .where(
            DrillAttempt.user_id == user_id,
            DrillAttempt.passed.is_(True),
        )
        .distinct()
    )
    passed_ids = {row[0] for row in passed_rows.all()}

    # Single ordered sweep over the course's drills. We join
    # ``drill_modules`` so the sort key covers both module and drill
    # order deterministically — picking the first unpassed drill is
    # then the next row in the iteration.
    stmt = (
        select(Drill)
        .join(DrillModule, DrillModule.id == Drill.module_id)
        .where(DrillModule.course_id == course.id)
        .order_by(DrillModule.order_index.asc(), Drill.order_index.asc())
    )
    for drill in (await db.execute(stmt)).scalars().all():
        if drill.id not in passed_ids:
            return drill
    return None


__all__ = ["select_next_drill"]
