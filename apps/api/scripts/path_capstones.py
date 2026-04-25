"""Backfill ``path_rooms.capstone_problem_ids`` with the 3 hardest tasks.

The capstone list is a precomputed Slice 2 affordance: later room UI can
launch a room's hardest tasks without re-ranking every problem on every
request. Ranking favors:

1. Higher ``difficulty_layer``
2. More hands-on ``question_type`` (lab/code over plain MC)
3. Later ``task_order`` inside the room
4. Later ``order_index`` as a final deterministic tiebreak
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_API_DIR = Path(__file__).resolve().parent.parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from database import async_session  # noqa: E402
from models.learning_path import PathRoom  # noqa: E402
from models.practice import (  # noqa: E402
    CODE_EXERCISE_TYPE,
    LAB_EXERCISE_TYPE,
    QUESTION_TYPE_APPLY,
    QUESTION_TYPE_COMPARE,
    QUESTION_TYPE_REBUILD,
    QUESTION_TYPE_TRACE,
    PracticeProblem,
)

_QUESTION_TYPE_WEIGHT = {
    LAB_EXERCISE_TYPE: 5,
    CODE_EXERCISE_TYPE: 4,
    QUESTION_TYPE_REBUILD: 3,
    QUESTION_TYPE_APPLY: 2,
    QUESTION_TYPE_COMPARE: 2,
    QUESTION_TYPE_TRACE: 1,
}


def _problem_rank(problem: PracticeProblem) -> tuple[int, int, int, int, str]:
    """Return a descending-sort key for capstone selection."""

    difficulty = int(problem.difficulty_layer or 0)
    question_weight = _QUESTION_TYPE_WEIGHT.get(problem.question_type, 0)
    task_order = int(problem.task_order if problem.task_order is not None else -1)
    order_index = int(problem.order_index or 0)
    return (
        difficulty,
        question_weight,
        task_order,
        order_index,
        str(problem.id),
    )


def select_capstone_problem_ids(
    problems: Iterable[PracticeProblem],
    *,
    limit: int = 3,
) -> list[str]:
    """Return up to ``limit`` problem ids ranked hardest-first."""

    ranked = sorted(problems, key=_problem_rank, reverse=True)
    return [str(problem.id) for problem in ranked[:limit]]


async def backfill_room_capstones(
    db: AsyncSession,
    *,
    room_ids: Iterable[uuid.UUID] | None = None,
    limit: int = 3,
) -> int:
    """Populate capstone ids for every selected room and return updates."""

    stmt = select(PathRoom).order_by(PathRoom.room_order.asc(), PathRoom.id.asc())
    if room_ids is not None:
        room_id_list = list(room_ids)
        if not room_id_list:
            return 0
        stmt = stmt.where(PathRoom.id.in_(room_id_list))

    rooms = (await db.execute(stmt)).scalars().all()
    updated = 0
    for room in rooms:
        tasks = (
            (
                await db.execute(
                    select(PracticeProblem)
                    .where(PracticeProblem.path_room_id == room.id)
                    .order_by(
                        PracticeProblem.task_order.is_(None),
                        PracticeProblem.task_order.asc(),
                        PracticeProblem.order_index.asc(),
                        PracticeProblem.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not tasks:
            # Empty room: leave column untouched. A future seed run
            # may add tasks; until then None signals "no capstone yet"
            # without churning re-runs.
            continue
        capstone_ids = select_capstone_problem_ids(tasks, limit=limit)
        if room.capstone_problem_ids != capstone_ids:
            room.capstone_problem_ids = capstone_ids
            updated += 1
    return updated


async def main(
    *,
    dry_run: bool = False,
    session_factory=async_session,
    limit: int = 3,
) -> int:
    """Backfill capstones for every room in the DB."""

    async with session_factory() as db:
        updated = await backfill_room_capstones(db, limit=limit)
        if dry_run:
            await db.rollback()
            print(f"[DRY RUN] Would update capstones for {updated} room(s)")
        else:
            await db.commit()
            print(f"Updated capstones for {updated} room(s)")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(dry_run=args.dry_run, limit=args.limit)))
