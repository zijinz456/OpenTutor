"""Seed the python-foundations LearningPath from a structured YAML.

Unlike ``seed_python_paths.py`` (which backfills existing scraped
``practice_problems`` by URL), this script is the source of truth for
*hand-curated* Python curriculum: it creates the path, rooms, and
practice_problems from scratch, ingesting each yaml task as a fully
realised ``PracticeProblem`` row with question/options/refsol/etc.

YAML schema (subset):

    track:
      slug: python-foundations
      title: Python Foundations
      description: ...

    missions:
      - slug: variables-and-strings
        title: Variables, Strings, Type Conversion
        intro: 1-2 sentence concept blurb
        tasks:
          - type: code | mc | tf | short_answer
            prompt: ...
            # code: starter, refsol, tests (list), hints (list)
            # mc: options ({A,B,C,D}), correct ("A".."D"), explanation
            # tf: correct (bool), explanation
            # short_answer: accepted_answers (list), explanation

Idempotent on re-run: path is upserted by slug; rooms by (path_id,
slug). Tasks are matched to existing rows by ``(path_room_id,
task_order)`` and updated in place, preserving ``PracticeProblem.id``
so that historical ``PracticeResult`` rows stay attached. Extra rows
beyond the yaml's task list are flagged ``is_archived=True`` rather
than deleted — recall-trainer history is more valuable than a clean
truncate.

Usage::

    docker exec -i opentutor-api python -m scripts.seed_python_foundations \\
        --yaml /app/content/python-foundations/v1.0.0/course.yaml

    # Validation-only (no DB writes), useful as a CI shape check:
    docker exec -i opentutor-api python -m scripts.seed_python_foundations \\
        --yaml /app/content/python-foundations/v1.0.0/course.yaml --validate-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any, cast

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_API_DIR = Path(__file__).resolve().parent.parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from database import async_session  # noqa: E402
from models.course import Course  # noqa: E402
from models.learning_path import LearningPath, PathRoom  # noqa: E402
from models.practice import PracticeProblem  # noqa: E402
from models.user import User  # noqa: E402

DEFAULT_YAML = "/app/content/python-foundations/v1.0.0/course.yaml"
COURSE_NAME = "Python Foundations"

# Required keys per task type. Validator surfaces the missing key with
# the mission slug + task index so authoring errors are pinpointed
# without grepping through 248 tasks.
_REQUIRED_TASK_KEYS: dict[str, tuple[str, ...]] = {
    "code": ("prompt", "refsol", "tests"),
    "mc": ("prompt", "options", "correct"),
    "tf": ("prompt", "correct"),
    "short_answer": ("prompt", "accepted_answers"),
}


class CurriculumValidationError(ValueError):
    """Raised when the curriculum yaml is structurally invalid.

    The message format is intentional — every error names the mission
    slug and the 0-based task index so authors can jump straight to the
    offending section without scanning the file.
    """


def _validate_curriculum(data: dict[str, Any]) -> tuple[int, int]:
    """Walk the yaml once before any DB write. Returns (missions, tasks).

    Raises :class:`CurriculumValidationError` on the first structural
    problem with enough context (mission slug + task index + missing
    key) to fix authoring without re-running the seeder.
    """

    if not isinstance(data, dict):
        raise CurriculumValidationError(
            f"top-level yaml must be a mapping, got {type(data).__name__}"
        )

    track = data.get("track")
    if not isinstance(track, dict):
        raise CurriculumValidationError("missing 'track' mapping at top level")
    for key in ("slug", "title"):
        if not track.get(key):
            raise CurriculumValidationError(f"track.{key} is required and non-empty")

    missions = data.get("missions")
    if not isinstance(missions, list) or not missions:
        raise CurriculumValidationError("'missions' must be a non-empty list")

    total_tasks = 0
    for m_idx, mission_obj in enumerate(missions):
        if not isinstance(mission_obj, dict):
            raise CurriculumValidationError(
                f"missions[{m_idx}] must be a mapping, got {type(mission_obj).__name__}"
            )
        # cast() is a runtime no-op but tells ty the dict has str keys —
        # ``isinstance(x, dict)`` only narrows to ``dict[Unknown, Unknown]``
        # and dict's first type parameter is invariant, so a plain
        # annotation refuses to widen.
        mission = cast(dict[str, Any], mission_obj)
        slug = mission.get("slug")
        if not slug:
            raise CurriculumValidationError(
                f"missions[{m_idx}].slug is required and non-empty"
            )
        if not mission.get("title"):
            raise CurriculumValidationError(
                f"mission='{slug}': title is required and non-empty"
            )

        tasks_obj = mission.get("tasks", [])
        if not isinstance(tasks_obj, list):
            raise CurriculumValidationError(
                f"mission='{slug}': tasks must be a list, "
                f"got {type(tasks_obj).__name__}"
            )
        tasks = cast(list[Any], tasks_obj)

        for t_idx, task_obj in enumerate(tasks):
            if not isinstance(task_obj, dict):
                raise CurriculumValidationError(
                    f"mission='{slug}' task[{t_idx}]: "
                    f"must be a mapping, got {type(task_obj).__name__}"
                )
            task = cast(dict[str, Any], task_obj)
            ttype = task.get("type")
            if ttype not in _REQUIRED_TASK_KEYS:
                raise CurriculumValidationError(
                    f"mission='{slug}' task[{t_idx}]: "
                    f"unknown type {ttype!r}; expected one of "
                    f"{sorted(_REQUIRED_TASK_KEYS)}"
                )
            required = _REQUIRED_TASK_KEYS[ttype]
            missing = [key for key in required if key not in task]
            if missing:
                raise CurriculumValidationError(
                    f"mission='{slug}' task[{t_idx}] type={ttype}: "
                    f"missing required key(s): {missing}"
                )
            total_tasks += 1

    return len(missions), total_tasks


async def _get_or_create_user(db: AsyncSession) -> uuid.UUID:
    """Return the single-user fallback uuid, creating it if missing.

    The User model exposes a ``name`` field (not ``display_name``) — see
    ``models/user.py``. Earlier revisions of this seeder used
    ``display_name=`` which fails at constructor time.
    """

    res = await db.execute(select(User).order_by(User.created_at).limit(1))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(
            id=uuid.uuid4(),
            email="local@learndopamine.local",
            name="Local",
        )
        db.add(user)
        await db.flush()
    return user.id


async def _get_or_create_course(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    """Return the python-foundations Course id, creating one if absent."""
    res = await db.execute(select(Course).where(Course.name == COURSE_NAME))
    course = res.scalar_one_or_none()
    if course is None:
        course = Course(
            id=uuid.uuid4(),
            user_id=user_id,
            name=COURSE_NAME,
            description="CS50P-equivalent hand-curated Python curriculum.",
        )
        db.add(course)
        await db.flush()
    return course.id


async def _upsert_path(db: AsyncSession, track: dict) -> LearningPath:
    res = await db.execute(
        select(LearningPath).where(LearningPath.slug == track["slug"])
    )
    path = res.scalar_one_or_none()
    if path is None:
        path = LearningPath(
            id=uuid.uuid4(),
            slug=track["slug"],
            title=track["title"],
            difficulty="beginner",
            track_id=track["slug"].replace("-", "_"),
            description=track.get("description"),
            room_count_target=0,
        )
        db.add(path)
        await db.flush()
    else:
        path.title = track["title"]
        path.description = track.get("description")
    return path


async def _upsert_room(
    db: AsyncSession, path: LearningPath, mission: dict, order: int
) -> PathRoom:
    res = await db.execute(
        select(PathRoom).where(
            PathRoom.path_id == path.id, PathRoom.slug == mission["slug"]
        )
    )
    room = res.scalar_one_or_none()
    if room is None:
        room = PathRoom(
            id=uuid.uuid4(),
            path_id=path.id,
            slug=mission["slug"],
            title=mission["title"],
            room_order=order,
            intro_excerpt=mission.get("intro"),
            outcome=mission.get("outcome"),
            eta_minutes=mission.get("eta_minutes", 15),
            task_count_target=len(mission.get("tasks", [])),
        )
        db.add(room)
        await db.flush()
    else:
        room.title = mission["title"]
        room.room_order = order
        room.intro_excerpt = mission.get("intro")
        room.eta_minutes = mission.get("eta_minutes", 15)
        room.task_count_target = len(mission.get("tasks", []))
    return room


def _apply_task_fields(problem: PracticeProblem, task: dict, order: int) -> None:
    """Mutate ``problem`` in place with the fields from ``task``.

    Called from both the insert and update paths so the row layout stays
    in one place. Always clears ``is_archived`` because if a row is
    being filled from yaml it's by definition still part of the curated
    set.
    """

    ttype = task["type"]
    problem.task_order = order
    problem.order_index = order
    problem.is_archived = False
    problem.source = "ai_generated"
    problem.source_owner = "ai"

    if ttype == "code":
        problem.question_type = "code_exercise"
        problem.question = task["prompt"]
        problem.correct_answer = None
        problem.explanation = None
        problem.options = None
        problem.problem_metadata = {
            "starter_code": task.get("starter", ""),
            "reference_solution": task.get("refsol", ""),
            "tests": task.get("tests", []),
            "hints": task.get("hints", []),
        }
    elif ttype == "mc":
        problem.question_type = "mc"
        problem.question = task["prompt"]
        problem.options = task.get("options", {})
        problem.correct_answer = task.get("correct")
        problem.explanation = task.get("explanation")
        problem.problem_metadata = None
    elif ttype == "tf":
        problem.question_type = "tf"
        problem.question = task["prompt"]
        problem.options = None
        problem.correct_answer = "true" if task.get("correct") else "false"
        problem.explanation = task.get("explanation")
        problem.problem_metadata = None
    elif ttype == "short_answer":
        accepted = task.get("accepted_answers", [])
        primary = accepted[0] if accepted else ""
        problem.question_type = "short_answer"
        problem.question = task["prompt"]
        problem.options = None
        problem.correct_answer = primary
        problem.explanation = task.get("explanation")
        problem.problem_metadata = {"accepted_answers": accepted}
    else:
        # Validator catches this earlier; the branch is defensive only.
        raise CurriculumValidationError(f"Unknown task type: {ttype}")


def _new_problem(
    course_id: uuid.UUID, room_id: uuid.UUID, task: dict, order: int
) -> PracticeProblem:
    """Construct a fresh ``PracticeProblem`` row for a yaml task."""

    problem = PracticeProblem(
        id=uuid.uuid4(),
        course_id=course_id,
        path_room_id=room_id,
    )
    _apply_task_fields(problem, task, order)
    return problem


async def _upsert_room_tasks(
    db: AsyncSession,
    course_id: uuid.UUID,
    room: PathRoom,
    tasks: list[dict],
) -> dict[str, int]:
    """Upsert ``tasks`` into ``room`` preserving existing row IDs.

    Strategy:
      * Existing rows are matched by ``(path_room_id, task_order)`` —
        the same key we sort by in the room-detail UI.
      * If yaml provides a task at index ``i`` and a row exists at
        ``task_order=i``, mutate that row in place (its ``id`` stays
        stable so all attached :class:`PracticeResult` rows still
        point at the correct problem).
      * If yaml provides MORE tasks than the DB has, INSERT the extras.
      * If yaml provides FEWER tasks than the DB has, mark the trailing
        rows ``is_archived=True`` instead of deleting them — recall
        history is the whole point of the trainer.

    Returns the per-room counter so callers can build a summary.
    """

    res = await db.execute(
        select(PracticeProblem)
        .where(PracticeProblem.path_room_id == room.id)
        .order_by(PracticeProblem.task_order.asc())
    )
    existing: list[PracticeProblem] = list(res.scalars().all())
    by_order: dict[int, PracticeProblem] = {}
    for row in existing:
        # ``task_order`` is nullable in the schema (SQLite accepts None),
        # but every row this seeder writes carries an integer. Defensively
        # skip None-ordered rows so a legacy import doesn't shadow a
        # legitimate slot.
        if row.task_order is None:
            continue
        by_order[row.task_order] = row

    inserted = 0
    updated = 0
    archived = 0

    for i, task in enumerate(tasks):
        existing_row = by_order.get(i)
        if existing_row is None:
            db.add(_new_problem(course_id, room.id, task, i))
            inserted += 1
        else:
            _apply_task_fields(existing_row, task, i)
            updated += 1

    # Anything beyond the yaml's task list — archive instead of delete.
    yaml_len = len(tasks)
    for row in existing:
        if row.task_order is not None and row.task_order >= yaml_len:
            if not row.is_archived:
                row.is_archived = True
                archived += 1

    await db.flush()
    return {
        "inserted": inserted,
        "updated": updated,
        "archived": archived,
        "total": inserted + updated,
    }


async def main(yaml_path: str, *, validate_only: bool = False) -> dict[str, Any]:
    """Seed the python-foundations curriculum from yaml.

    With ``validate_only=True`` we walk the yaml + return its shape
    without touching the DB. Useful as a quick "is the file authored
    correctly?" check that doesn't require a running container.
    """

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    n_missions, n_tasks = _validate_curriculum(data)

    if validate_only:
        return {
            "validate_only": True,
            "yaml_path": yaml_path,
            "missions": n_missions,
            "tasks": n_tasks,
        }

    track = data["track"]
    missions = data["missions"]

    summary: dict[str, Any] = {
        "path_slug": track["slug"],
        "rooms": 0,
        "tasks": 0,
        "inserted": 0,
        "updated": 0,
        "archived": 0,
        "per_mission": [],
    }

    async with async_session() as db:
        user_id = await _get_or_create_user(db)
        course_id = await _get_or_create_course(db, user_id)
        path = await _upsert_path(db, track)

        for order, mission in enumerate(missions):
            room = await _upsert_room(db, path, mission, order)
            counts = await _upsert_room_tasks(
                db, course_id, room, mission.get("tasks", [])
            )
            summary["rooms"] += 1
            summary["tasks"] += counts["total"]
            summary["inserted"] += counts["inserted"]
            summary["updated"] += counts["updated"]
            summary["archived"] += counts["archived"]
            summary["per_mission"].append(
                {
                    "slug": mission["slug"],
                    "tasks": counts["total"],
                    "inserted": counts["inserted"],
                    "updated": counts["updated"],
                    "archived": counts["archived"],
                }
            )

        path.room_count_target = summary["rooms"]
        await db.commit()

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yaml", default=DEFAULT_YAML)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the yaml shape and exit without DB writes.",
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(main(args.yaml, validate_only=args.validate_only))
    except CurriculumValidationError as exc:
        print(f"curriculum validation error: {exc}", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(result, indent=2))
