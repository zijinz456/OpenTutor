"""Room/mission completion detector — Phase 16c Bundle B (Subagent B).

Detects when a user has just finished every task in a ``PathRoom`` and
awards the corresponding ``room_complete`` (or
``hacking_room_complete``) XP event idempotently.

Why a separate module
---------------------
``services/path_room_factory.py`` owns *creating* rooms; this module
owns *detecting completion* of an existing room. Mixing the two would
muddy the factory's purpose. The pure-function awarders live in
``services/xp_service.py`` (Subagent A scope) — this module is the
glue: read the user's progress, decide if the room is done, look up
the hacking flag, then call the awarder.

Idempotence
-----------
``award_room_xp`` rides on the ``xp_events`` UNIQUE
``(user_id, source_id, date(earned_at))`` index. A second call for the
same room on the same UTC day returns ``None`` from the awarder; we
surface that ``None`` to our caller unchanged. Story 2 #4 says XP
plumbing must never fail the caller's transaction — we wrap the
awarder in a defensive ``try/except`` and log-and-swallow.

Wiring
------
Subagent A's ``services/quiz_submission.py`` calls
``maybe_award_room_completion_xp`` after card-XP awarding on every
submit. The helper is a no-op when the room is not yet complete, so
calling it on every submission is cheap and correct.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.learning_path import LearningPath, PathRoom
from models.practice import PracticeProblem, PracticeResult
from models.xp_event import XpEvent
from services.xp_service import award_room_xp


_log = logging.getLogger(__name__)


async def is_room_complete(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    path_room_id: uuid.UUID,
) -> tuple[bool, int]:
    """Return ``(complete, task_count)`` for a user × room pair.

    Complete iff every ``PracticeProblem`` in the room has at least one
    correct ``PracticeResult`` row for ``user_id``. An empty room is
    *not* complete (returns ``(False, 0)``) — completing a zero-task
    room would award 0 XP and is meaningless.

    Implementation: a single SQL trip. We compute the total task count
    and the user's distinct-completed count in two parallel scalar
    subqueries on the same execution. Two subqueries are clearer than
    a CTE here and the planner emits the same shape on SQLite/Postgres.
    """
    total_stmt = select(func.count(PracticeProblem.id)).where(
        PracticeProblem.path_room_id == path_room_id
    )
    completed_stmt = (
        select(func.count(func.distinct(PracticeProblem.id)))
        .select_from(PracticeProblem)
        .join(PracticeResult, PracticeResult.problem_id == PracticeProblem.id)
        .where(
            PracticeProblem.path_room_id == path_room_id,
            PracticeResult.user_id == user_id,
            PracticeResult.is_correct.is_(True),
        )
    )
    total = int((await db.execute(total_stmt)).scalar_one() or 0)
    completed = int((await db.execute(completed_stmt)).scalar_one() or 0)
    is_complete = total > 0 and completed >= total
    return is_complete, total


async def maybe_award_room_completion_xp(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    path_room_id: uuid.UUID,
) -> Optional[XpEvent]:
    """Award room-completion XP iff the user has now finished the room.

    Returns the inserted ``XpEvent`` on success, or ``None`` when:

    * the room is not yet complete (most common — every card submit
      lands here until the final correct answer);
    * the room id does not exist (defensive — should not happen in
      practice, but we don't blow up the caller);
    * the same-day dedup unique index rejects the insert (idempotent
      replay — a second completion of the same room within one UTC
      day is a no-op);
    * any other unexpected error in the awarder (we log and swallow
      so the caller's practice-result transaction stays clean).

    Hacking flag is derived from the parent path's ``track_id``: any
    track id containing the substring ``"hacking"`` (case-insensitive)
    is treated as a hacking track and uses the ×2 XP multiplier
    defined in ``services.xp_service.compute_xp``.
    """
    complete, task_count = await is_room_complete(
        db, user_id=user_id, path_room_id=path_room_id
    )
    if not complete:
        return None

    # Resolve hacking flag via PathRoom → LearningPath.track_id. Two
    # small selects rather than a join — this branch only runs on the
    # final card of a room, so an extra round-trip is negligible.
    room = (
        await db.execute(select(PathRoom).where(PathRoom.id == path_room_id))
    ).scalar_one_or_none()
    if room is None:
        return None
    path = (
        await db.execute(select(LearningPath).where(LearningPath.id == room.path_id))
    ).scalar_one_or_none()
    is_hacking = bool(path and path.track_id and "hacking" in path.track_id.lower())

    try:
        evt = await award_room_xp(
            db,
            user_id=user_id,
            room_id=path_room_id,
            task_count=task_count,
            is_hacking=is_hacking,
        )
    except Exception as exc:  # noqa: BLE001 — Story 2 #4: never fail caller
        _log.warning(
            "room_completion: award_room_xp raised; swallowing "
            "user_id=%s room_id=%s err=%s",
            user_id,
            path_room_id,
            exc,
        )
        return None

    # Phase 16c Bundle C — fire badge evaluator on the SAME event so
    # ``first_room_completed`` / ``python_fluent`` / ``hacker_novice`` /
    # track-XP-threshold badges unlock right at room-completion time
    # (rather than waiting for the next card submit). Lazy import +
    # swallow-and-log keeps the awarder strictly non-blocking — a bug in
    # any predicate must NEVER swallow the XP event we just awarded.
    if evt is not None:
        try:
            from services.gamification.badge_service import award_all_eligible

            await award_all_eligible(db, user_id=user_id)
        except Exception as exc:  # noqa: BLE001 — never fail caller
            _log.warning(
                "room_completion: award_all_eligible raised; swallowing "
                "user_id=%s room_id=%s err=%s",
                user_id,
                path_room_id,
                exc,
            )

    return evt
