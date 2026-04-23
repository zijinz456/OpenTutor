"""Learning-path progress helpers — Phase 16a T3 Python Paths UI.

Per critic C5 in ``plan/python_paths_ui_phase16a.md``, per-user path
progress is **derived** from ``PracticeResult`` rows rather than
materialised in a second table. These helpers encapsulate the two
queries the router needs:

* :func:`get_completed_task_ids` — the set of problem ids the user has
  answered correctly at least once (a card "counts as done" the first
  time it's green, regardless of subsequent reviews).
* :func:`get_room_task_counts` — batched total-tasks-per-room lookup, so
  the list endpoint doesn't issue one COUNT per room.

Kept here (not inline in the router) so unit tests can exercise the
aggregation without spinning up a FastAPI app, and so future callers
(capstone gate, path-complete notifications in P1) share the same
definition of "done".
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.practice import PracticeProblem, PracticeResult


async def get_completed_task_ids(
    db: AsyncSession, user_id: uuid.UUID
) -> set[uuid.UUID]:
    """Return the set of ``problem_id`` values the user has answered correctly.

    A card is "complete" if the user has at least one ``PracticeResult``
    row with ``is_correct=True`` for it — the FSRS reset / re-review
    flow may later add more rows, but the first green answer is what
    marks the task done for the TryHackMe-style checkbox. DISTINCT at
    the DB keeps the payload small even when a card has been answered
    many times.
    """

    stmt = (
        select(PracticeResult.problem_id)
        .where(
            PracticeResult.user_id == user_id,
            PracticeResult.is_correct.is_(True),
        )
        .distinct()
    )
    rows = await db.execute(stmt)
    return {row[0] for row in rows.all()}


async def get_room_task_counts(
    db: AsyncSession, room_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Return ``{room_id: total_tasks}`` for the supplied room ids.

    Single ``COUNT(*) … GROUP BY path_room_id`` instead of per-room
    fan-out — the list endpoint calls this once with every room on the
    page. Rooms with zero mapped tasks are absent from the result
    (caller treats missing as 0); this matches the yaml-target vs
    actually-mapped-cards split the dashboard surfaces as "3/15 tasks".
    """

    if not room_ids:
        return {}
    stmt = (
        select(PracticeProblem.path_room_id, func.count(PracticeProblem.id))
        .where(PracticeProblem.path_room_id.in_(room_ids))
        .group_by(PracticeProblem.path_room_id)
    )
    rows = await db.execute(stmt)
    # SQLAlchemy returns the grouped column as the first tuple element;
    # it is never NULL here because the WHERE clause excludes orphans.
    return {row[0]: row[1] for row in rows.all()}


async def count_orphan_cards(db: AsyncSession) -> int:
    """Return the total number of practice problems without a ``path_room_id``.

    "Orphan" means a card lives in the content corpus but isn't yet
    attached to any path room — seeding only maps cards whose parent
    ``CourseContentTree.source_file`` matches a curated yaml URL, so
    the current live DB has 249 mapped / 332 orphan on a 581-card
    course. The dashboard surfaces this so Юрій knows there is still
    unmapped content without having to read the seed script's log.
    """

    stmt = select(func.count(PracticeProblem.id)).where(
        PracticeProblem.path_room_id.is_(None)
    )
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def sample_orphan_cards(db: AsyncSession, limit: int = 10) -> list[dict]:
    """Return up to ``limit`` orphan problems as ``{id, question}`` dicts.

    Used by ``GET /api/paths/orphans`` to power the dashboard caption —
    the first ten orphan card titles are enough context for Юрій to
    recognise a cluster ("все з розділу X") without shipping the full
    332-row payload. ``question`` is the flashcard front / MC prompt;
    we trim to the first 80 chars so long free-response prompts don't
    dominate the response.
    """

    stmt = (
        select(PracticeProblem.id, PracticeProblem.question)
        .where(PracticeProblem.path_room_id.is_(None))
        .order_by(PracticeProblem.created_at.asc())
        .limit(limit)
    )
    rows = await db.execute(stmt)
    return [
        {
            "id": str(row[0]),
            "title": (row[1] or "").strip()[:80],
        }
        for row in rows.all()
    ]


__all__ = [
    "count_orphan_cards",
    "get_completed_task_ids",
    "get_room_task_counts",
    "sample_orphan_cards",
]
