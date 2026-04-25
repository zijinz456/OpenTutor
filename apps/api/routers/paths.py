"""Learning paths HTTP surface — Phase 16a T3 Python Paths UI.

Four endpoints under ``/api/paths``:

* ``GET /api/paths``                         — summary list for the dashboard.
* ``GET /api/paths/orphans``                 — unmapped-card count + sample.
* ``GET /api/paths/{slug}``                  — single path + its rooms.
* ``GET /api/paths/{slug}/rooms/{room_id}``  — single room + its tasks.

Per the plan, tracks are **parallel** in P0 — no unlock gate between
tracks or between rooms within a track. All rooms are accessible; the
progress fields (``room_complete`` / ``task_complete``) are
informational. Skip-room override and capstone gating land in P1.

Progress is derived from ``PracticeResult`` rows (critic C5: no
``user_path_progress`` table), via helpers in
:mod:`services.learning_paths`.

Ordering note: ``/api/paths/orphans`` is declared **before** the
parameterised ``/{slug}`` route so FastAPI matches ``orphans`` as the
literal path, not a slug. Re-ordering the decorators would break
``GET /api/paths/orphans``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from database import async_session, get_db
from models.course import Course
from models.learning_path import LearningPath, PathRoom
from models.practice import PracticeProblem
from models.user import User
from schemas.path_generation import (
    GenerateRoomRequest,
    validate_topic,
)
from services.auth.dependency import get_current_user
from services.learning_paths import (
    count_orphan_cards,
    get_completed_task_ids,
    get_room_progress_snapshots,
    get_room_task_counts,
    resolve_room_intro_excerpt,
    sample_orphan_cards,
)

# Phase 16b factory + job store live in the service layer (Subagent A
# scope). The factory's ``generate_and_persist_room`` is the public
# entry point for both stages of generation; ``compute_generation_seed``
# is reused at the router level so we can short-circuit on idempotent
# reuse before touching the LLM. The job store is exposed as a set of
# module-level coroutines (``create_job`` / ``update_status`` /
# ``subscribe`` / ``get``) — no singleton class.
from services import path_room_job_store as job_store
from services.path_room_factory import (
    IDEMPOTENCE_WINDOW,
    compute_generation_seed,
    generate_and_persist_room,
)

logger = logging.getLogger(__name__)

# Daily generation cap (Part E of the spec). Single-user local-first
# posture means we count generated PathRoom rows directly rather than
# adding a new quota table.
_DAILY_GENERATION_CAP: int = 5

router = APIRouter()


# ── Response schemas (inline — scoped to this router) ───────────────


class PathSummary(BaseModel):
    """One path row on the dashboard list."""

    id: uuid.UUID
    slug: str
    title: str
    difficulty: str
    track_id: str
    description: Optional[str] = None
    room_total: int = Field(..., ge=0)
    room_complete: int = Field(..., ge=0)
    task_total: int = Field(..., ge=0)
    task_complete: int = Field(..., ge=0)
    # Informational mirror of the top-level orphan count — duplicated
    # on each row so a client rendering a single card (e.g. a deep
    # link) still has the context number without a second request.
    orphan_count: int = Field(..., ge=0)


class PathListResponse(BaseModel):
    """Payload for ``GET /api/paths``."""

    paths: list[PathSummary]
    # Sum of orphan cards across all tracks — the "N cards not yet in
    # any path" dashboard caption uses this number (critic C2).
    orphan_count: int = Field(..., ge=0)


class RoomSummary(BaseModel):
    """One row inside ``PathDetailResponse.rooms``."""

    id: uuid.UUID
    slug: str
    title: str
    room_order: int = Field(..., ge=0)
    task_total: int = Field(..., ge=0)
    task_complete: int = Field(..., ge=0)
    intro_excerpt: Optional[str] = None
    outcome: Optional[str] = None
    difficulty: Optional[int] = Field(default=None, ge=1, le=5)
    eta_minutes: Optional[int] = Field(default=None, ge=1)
    module_label: Optional[str] = None


class PathDetailResponse(BaseModel):
    """Payload for ``GET /api/paths/{slug}``."""

    id: uuid.UUID
    slug: str
    title: str
    difficulty: str
    track_id: str
    description: Optional[str] = None
    rooms: list[RoomSummary]
    room_total: int = Field(..., ge=0)
    room_complete: int = Field(..., ge=0)


class RoomTask(BaseModel):
    """One card inside ``RoomDetailResponse.tasks``.

    Intentionally omits ``correct_answer`` / ``explanation`` — the
    client shouldn't be able to peek at the answer by reading network
    traffic before submitting. Those fields come back via the separate
    grading endpoint after a submission.
    """

    id: uuid.UUID
    task_order: Optional[int] = None
    question_type: str
    question: str
    options: Optional[dict] = None
    is_complete: bool
    difficulty_layer: Optional[int] = None


class RoomDetailResponse(BaseModel):
    """Payload for ``GET /api/paths/{slug}/rooms/{room_id}``.

    Slice 2 extensions
    ------------------
    * ``intro_excerpt`` is now resolved from real ``CourseContentTree``
      prose when available (see ``resolve_room_intro_excerpt``), falling
      back to the column value and finally ``None``.
    * ``capstone_problem_ids`` exposes the up-to-3 hardest-task ids for
      the room's checkpoint launcher. Always a list — empty when the
      column is NULL / missing so frontend consumers can iterate without
      a null check. Defaults to ``[]`` so older Codex-B-free clients
      still deserialise without schema drift.
    """

    id: uuid.UUID
    slug: str
    title: str
    room_order: int
    intro_excerpt: Optional[str] = None
    outcome: Optional[str] = None
    difficulty: Optional[int] = Field(default=None, ge=1, le=5)
    eta_minutes: Optional[int] = Field(default=None, ge=1)
    module_label: Optional[str] = None
    path_id: uuid.UUID
    path_slug: str
    path_title: str
    tasks: list[RoomTask]
    task_total: int = Field(..., ge=0)
    task_complete: int = Field(..., ge=0)
    capstone_problem_ids: list[str] = Field(default_factory=list)


class OrphanSample(BaseModel):
    """One entry in ``OrphanListResponse.sample``."""

    id: str
    title: str


class OrphanListResponse(BaseModel):
    """Payload for ``GET /api/paths/orphans``."""

    count: int = Field(..., ge=0)
    sample: list[OrphanSample]


class CurrentMissionResponse(BaseModel):
    """Payload for ``GET /api/paths/current-mission``."""

    mission_id: uuid.UUID
    path_id: uuid.UUID
    path_slug: str
    path_title: str
    title: str
    intro_excerpt: Optional[str] = None
    outcome: Optional[str] = None
    difficulty: Optional[int] = Field(default=None, ge=1, le=5)
    eta_minutes: Optional[int] = Field(default=None, ge=1)
    module_label: Optional[str] = None
    task_total: int = Field(..., ge=0)
    task_complete: int = Field(..., ge=0)
    progress_pct: int = Field(..., ge=0, le=100)


# ── Endpoint 1: GET /api/paths ──────────────────────────────────────


@router.get(
    "",
    response_model=PathListResponse,
    summary="List every learning path with aggregate progress",
    description=(
        "Returns one ``PathSummary`` per ``learning_paths`` row, with "
        "``room_total`` / ``room_complete`` / ``task_total`` / "
        "``task_complete`` derived live from ``PracticeResult`` for the "
        "current user. A room is ``complete`` when **every** task in it "
        "has at least one correct ``PracticeResult`` for this user. The "
        "top-level ``orphan_count`` mirrors every path's orphan field."
    ),
)
async def list_paths(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PathListResponse:
    """Return the dashboard list with progress counters."""

    paths_result = await db.execute(
        select(LearningPath).order_by(LearningPath.created_at.asc())
    )
    paths = list(paths_result.scalars().all())

    # One-shot room fetch for every path — ordered so we can group in
    # Python without a second SQL round-trip per path.
    path_ids = [p.id for p in paths]
    rooms_by_path: dict[uuid.UUID, list[PathRoom]] = {pid: [] for pid in path_ids}
    if path_ids:
        rooms_result = await db.execute(
            select(PathRoom)
            .where(PathRoom.path_id.in_(path_ids))
            .order_by(PathRoom.path_id, PathRoom.room_order)
        )
        for room in rooms_result.scalars().all():
            rooms_by_path[room.path_id].append(room)

    all_room_ids = [room.id for rooms in rooms_by_path.values() for room in rooms]
    tasks_per_room = await get_room_task_counts(db, all_room_ids)
    completed_ids = await get_completed_task_ids(db, user.id)

    # We need the per-room correct-count too. One more grouped query
    # keeps the list endpoint at O(1) DB hits regardless of room count.
    per_room_complete: dict[uuid.UUID, int] = {}
    if all_room_ids and completed_ids:
        completed_rows = await db.execute(
            select(
                PracticeProblem.path_room_id,
                func.count(PracticeProblem.id),
            )
            .where(
                PracticeProblem.path_room_id.in_(all_room_ids),
                PracticeProblem.id.in_(completed_ids),
            )
            .group_by(PracticeProblem.path_room_id)
        )
        per_room_complete = {row[0]: row[1] for row in completed_rows.all()}

    orphan_total = await count_orphan_cards(db)

    summaries: list[PathSummary] = []
    for path in paths:
        rooms = rooms_by_path.get(path.id, [])
        room_total = len(rooms)
        task_total = sum(tasks_per_room.get(r.id, 0) for r in rooms)
        task_complete = sum(per_room_complete.get(r.id, 0) for r in rooms)
        # A room counts as "complete" only when it has at least one
        # mapped task AND every one of those tasks is green — an empty
        # room is never retroactively marked done.
        room_complete = sum(
            1
            for r in rooms
            if tasks_per_room.get(r.id, 0) > 0
            and per_room_complete.get(r.id, 0) >= tasks_per_room.get(r.id, 0)
        )
        summaries.append(
            PathSummary(
                id=path.id,
                slug=path.slug,
                title=path.title,
                difficulty=path.difficulty,
                track_id=path.track_id,
                description=path.description,
                room_total=room_total,
                room_complete=room_complete,
                task_total=task_total,
                task_complete=task_complete,
                orphan_count=orphan_total,
            )
        )

    return PathListResponse(paths=summaries, orphan_count=orphan_total)


# ── Endpoint 4: GET /api/paths/orphans ──────────────────────────────
# Declared BEFORE ``/{slug}`` so FastAPI routes the literal ``orphans``
# segment correctly; otherwise ``slug="orphans"`` would be matched
# first and the endpoint would 404.


@router.get(
    "/orphans",
    response_model=OrphanListResponse,
    summary="Count and sample of cards not attached to any path room",
    description=(
        "Informational — the dashboard caption uses ``count`` to nudge "
        "Юрія that unmapped content still exists, and ``sample`` "
        "(first 10 titles) so he can recognise clusters. Cards are "
        "'orphan' when ``practice_problems.path_room_id IS NULL``."
    ),
)
async def list_orphans(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrphanListResponse:
    """Return total orphan count + a small sample of titles."""

    count = await count_orphan_cards(db)
    sample_rows = await sample_orphan_cards(db, limit=10)
    return OrphanListResponse(
        count=count,
        sample=[OrphanSample(**row) for row in sample_rows],
    )


# ── Endpoint 2: GET /api/paths/{slug} ───────────────────────────────


@router.get(
    "/current-mission",
    response_model=Optional[CurrentMissionResponse],
    summary="Return the user's freshest in-progress mission, if any",
    description=(
        "Derives the current mission from existing practice data only. "
        "A mission is eligible when it has at least one mapped task, at "
        "least one completed task, and is not yet fully complete. When "
        "multiple partial missions exist, the router returns the one "
        "with the latest user activity."
    ),
)
async def get_current_mission(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[CurrentMissionResponse]:
    """Return the freshest in-progress mission or ``None``."""

    rows = list(
        (
            await db.execute(
                select(PathRoom, LearningPath)
                .join(LearningPath, LearningPath.id == PathRoom.path_id)
                .order_by(LearningPath.created_at.asc(), PathRoom.room_order.asc())
            )
        ).all()
    )
    if not rows:
        return None

    room_ids = [room.id for room, _path in rows]
    progress_by_room = await get_room_progress_snapshots(db, user.id, room_ids)

    current: tuple[PathRoom, LearningPath, int, int, int] | None = None
    current_last_activity = None

    for room, path in rows:
        progress = progress_by_room.get(room.id)
        if progress is None or progress.task_total <= 0:
            continue
        if progress.task_complete <= 0 or progress.task_complete >= progress.task_total:
            continue
        if progress.last_activity_at is None:
            continue

        progress_pct = round((progress.task_complete / progress.task_total) * 100)
        if (
            current is None
            or current_last_activity is None
            or progress.last_activity_at > current_last_activity
        ):
            current = (
                room,
                path,
                progress.task_total,
                progress.task_complete,
                progress_pct,
            )
            current_last_activity = progress.last_activity_at

    if current is None:
        return None

    room, path, task_total, task_complete, progress_pct = current
    return CurrentMissionResponse(
        mission_id=room.id,
        path_id=path.id,
        path_slug=path.slug,
        path_title=path.title,
        title=room.title,
        intro_excerpt=room.intro_excerpt,
        outcome=room.outcome,
        difficulty=room.difficulty,
        eta_minutes=room.eta_minutes,
        module_label=room.module_label,
        task_total=task_total,
        task_complete=task_complete,
        progress_pct=progress_pct,
    )


@router.get(
    "/{slug}",
    response_model=PathDetailResponse,
    summary="Single path with ordered rooms + per-room progress",
    description=(
        "404 when ``slug`` does not match any ``learning_paths`` row. "
        "Rooms are returned in ``room_order`` ascending."
    ),
)
async def get_path_detail(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PathDetailResponse:
    """Return one path with its rooms + per-room task counters."""

    path = (
        await db.execute(select(LearningPath).where(LearningPath.slug == slug))
    ).scalar_one_or_none()
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "path_not_found", "slug": slug},
        )

    rooms_result = await db.execute(
        select(PathRoom)
        .where(PathRoom.path_id == path.id)
        .order_by(PathRoom.room_order.asc())
    )
    rooms = list(rooms_result.scalars().all())
    room_ids = [r.id for r in rooms]

    tasks_per_room = await get_room_task_counts(db, room_ids)
    completed_ids = await get_completed_task_ids(db, user.id)

    per_room_complete: dict[uuid.UUID, int] = {}
    if room_ids and completed_ids:
        completed_rows = await db.execute(
            select(
                PracticeProblem.path_room_id,
                func.count(PracticeProblem.id),
            )
            .where(
                PracticeProblem.path_room_id.in_(room_ids),
                PracticeProblem.id.in_(completed_ids),
            )
            .group_by(PracticeProblem.path_room_id)
        )
        per_room_complete = {row[0]: row[1] for row in completed_rows.all()}

    summaries = [
        RoomSummary(
            id=r.id,
            slug=r.slug,
            title=r.title,
            room_order=r.room_order,
            task_total=tasks_per_room.get(r.id, 0),
            task_complete=per_room_complete.get(r.id, 0),
            intro_excerpt=r.intro_excerpt,
            outcome=r.outcome,
            difficulty=r.difficulty,
            eta_minutes=r.eta_minutes,
            module_label=r.module_label,
        )
        for r in rooms
    ]

    room_complete = sum(
        1
        for r in rooms
        if tasks_per_room.get(r.id, 0) > 0
        and per_room_complete.get(r.id, 0) >= tasks_per_room.get(r.id, 0)
    )

    return PathDetailResponse(
        id=path.id,
        slug=path.slug,
        title=path.title,
        difficulty=path.difficulty,
        track_id=path.track_id,
        description=path.description,
        rooms=summaries,
        room_total=len(rooms),
        room_complete=room_complete,
    )


# ── Endpoint 3: GET /api/paths/{slug}/rooms/{room_id} ───────────────


@router.get(
    "/{path_slug}/rooms/{room_id}",
    response_model=RoomDetailResponse,
    summary="Single room with its tasks + per-task completion flag",
    description=(
        "Returns the room identified by ``room_id`` (scoped to "
        "``path_slug`` — a 404 fires when the room exists but belongs "
        "to a different path, so the URL is self-validating). Tasks "
        "are ordered by ``task_order`` ascending; ``NULL`` task_orders "
        "come last so seed-gap rooms still render deterministically."
    ),
)
async def get_room_detail(
    path_slug: str,
    room_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoomDetailResponse:
    """Return a single room + its tasks with per-user completion flag."""

    path = (
        await db.execute(select(LearningPath).where(LearningPath.slug == path_slug))
    ).scalar_one_or_none()
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "path_not_found", "slug": path_slug},
        )

    room = (
        await db.execute(
            select(PathRoom).where(
                PathRoom.id == room_id,
                PathRoom.path_id == path.id,
            )
        )
    ).scalar_one_or_none()
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "room_not_found",
                "path_slug": path_slug,
                "room_id": str(room_id),
            },
        )

    # ``task_order`` is nullable; ``nulls_last`` is expressed via a
    # secondary ``is_not_null`` sort key so both SQLite and Postgres
    # behave the same (SQLite has no explicit NULLS LAST clause pre-
    # 3.30 and the repo still supports older SQLite wheels).
    tasks_result = await db.execute(
        select(PracticeProblem)
        .where(PracticeProblem.path_room_id == room.id)
        .order_by(
            PracticeProblem.task_order.is_(None),
            PracticeProblem.task_order.asc(),
            PracticeProblem.id.asc(),
        )
    )
    tasks = list(tasks_result.scalars().all())
    completed_ids = await get_completed_task_ids(db, user.id)

    payload = [
        RoomTask(
            id=t.id,
            task_order=t.task_order,
            question_type=t.question_type,
            question=t.question,
            options=t.options,
            is_complete=t.id in completed_ids,
            difficulty_layer=t.difficulty_layer,
        )
        for t in tasks
    ]

    task_total = len(tasks)
    task_complete = sum(1 for t in tasks if t.id in completed_ids)

    # Slice 2: upgrade placeholder intro → first 300 chars of real lesson
    # prose when any mapped task points at a ``CourseContentTree`` node
    # with non-null content. Fallback to the seed placeholder so the UI
    # keeps showing *something* when a room has no mapped tasks yet.
    intro_excerpt = await resolve_room_intro_excerpt(
        db, room.id, placeholder=room.intro_excerpt
    )

    # ``capstone_problem_ids`` is a dirty-worktree column (Codex B track)
    # — the ORM attribute exists, the SQLite column was added via inline
    # ALTER, but the Alembic migration is uncommitted. ``getattr`` with a
    # None fallback keeps this endpoint safe for (a) older test DBs whose
    # ``create_all`` predates the attribute, (b) any future rollback of
    # the Codex B column. Always hand the client a list.
    raw_capstones = getattr(room, "capstone_problem_ids", None) or []
    capstone_problem_ids = [str(cid) for cid in raw_capstones]

    return RoomDetailResponse(
        id=room.id,
        slug=room.slug,
        title=room.title,
        room_order=room.room_order,
        intro_excerpt=intro_excerpt,
        outcome=room.outcome,
        difficulty=room.difficulty,
        eta_minutes=room.eta_minutes,
        module_label=room.module_label,
        path_id=path.id,
        path_slug=path.slug,
        path_title=path.title,
        tasks=payload,
        task_total=task_total,
        task_complete=task_complete,
        capstone_problem_ids=capstone_problem_ids,
    )


# ── Endpoint 5: POST /api/paths/generate-room (Phase 16b) ──────────


def _topic_guard_400(error_code: str = "topic_guard") -> HTTPException:
    """Stable 400 envelope for topic-guard rejections."""

    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": error_code},
    )


async def _count_generated_rooms_today(db: AsyncSession) -> int:
    """Return how many ``room_type='generated'`` rooms exist for today (UTC).

    Spec Part E: derive the per-day cap from existing ``path_rooms``
    rows so we don't introduce a new quota table for the single-user
    posture. ``generated_at`` is timezone-aware in Postgres and naive-
    UTC in SQLite (the engine's UTC adapter — see ``database.py``); we
    bracket the day with ``[start, end)`` and let SQLAlchemy compare
    against either flavour without a backend-specific date function.
    """

    today_utc = datetime.now(timezone.utc).date()
    day_start = datetime.combine(today_utc, datetime.min.time(), tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    result = await db.execute(
        select(func.count(PathRoom.id)).where(
            PathRoom.room_type == "generated",
            PathRoom.generated_at.is_not(None),
            PathRoom.generated_at >= day_start,
            PathRoom.generated_at < day_end,
        )
    )
    return int(result.scalar() or 0)


@router.post(
    "/generate-room",
    summary="Schedule a standard-room generation (or reuse a recent one)",
    description=(
        "Validates the request, enforces topic guard + ownership + the "
        "path/course coherence constraint, and either:\n\n"
        "* returns ``200 {reused: true, room_id, path_id}`` when a "
        "generated room with the same ``generation_seed`` was created "
        "in the last hour, **or**\n"
        "* schedules a background generation job and returns ``202 "
        "{job_id, reused: false}``.\n\n"
        "Progress events for the 202 path are streamed at "
        "``GET /api/paths/generate-room/stream/{job_id}``."
    ),
)
async def generate_room(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Validate + (reuse or schedule) a standard-room generation."""

    # Parse the body manually so the topic-guard rejection comes back
    # as a 400 with a stable ``error`` code instead of Pydantic's
    # default 422 envelope. ``GenerateRoomRequest`` still runs Pydantic
    # validation for the rest of the body (uuids, difficulty literal,
    # task_count range, extra="forbid").
    try:
        raw = await request.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_json"},
        ) from exc

    if isinstance(raw, dict) and "topic" in raw:
        try:
            validate_topic(raw["topic"]) if isinstance(raw["topic"], str) else None
        except ValueError as exc:
            raise _topic_guard_400(str(exc)) from exc

    try:
        body = GenerateRoomRequest.model_validate(raw)
    except ValidationError as exc:
        # Map a topic-validator failure (which Pydantic raises as a
        # ValidationError wrapping our ValueError) to the same 400
        # envelope the explicit pre-check uses, so callers see one
        # consistent shape regardless of which path tripped the guard.
        for err in exc.errors():
            if err.get("loc") and err["loc"][0] == "topic":
                raise _topic_guard_400("topic_guard") from exc
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc

    # ── Resolve the path ──
    path = (
        await db.execute(select(LearningPath).where(LearningPath.id == body.path_id))
    ).scalar_one_or_none()
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "path_not_found", "path_id": str(body.path_id)},
        )

    # ── Resolve the course (must be owned by current user) ──
    course = (
        await db.execute(
            select(Course).where(
                Course.id == body.course_id,
                Course.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "course_not_found", "course_id": str(body.course_id)},
        )

    # ── Coherence: path × course must already share at least one task.
    # ``LearningPath`` has no direct ``course_id`` column, so we prove
    # the link via an existing ``PracticeProblem`` row. This rejects
    # the "owned course but unrelated path" combination instead of
    # silently persisting orphan tasks.
    coherence = (
        await db.execute(
            select(PracticeProblem.id)
            .join(PathRoom, PathRoom.id == PracticeProblem.path_room_id)
            .where(
                PathRoom.path_id == body.path_id,
                PracticeProblem.course_id == body.course_id,
            )
            .limit(1)
        )
    ).first()
    if coherence is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "path_course_mismatch"},
        )

    # ── Daily cap (Part E) ──
    generated_today = await _count_generated_rooms_today(db)
    if generated_today >= _DAILY_GENERATION_CAP:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "daily_generation_cap_exceeded"},
        )

    # ── Idempotence: reuse a recent generated room with the same seed ──
    # Subagent A's factory has the same logic in ``_find_existing_by_seed``,
    # but we must perform the check here BEFORE calling ``create_job`` so
    # the reuse path returns 200 without scheduling a worker. Mirroring
    # the factory's lookup keeps the canonical-form rules in one place
    # (``compute_generation_seed`` + ``IDEMPOTENCE_WINDOW``).
    seed = compute_generation_seed(
        user_id=user.id,
        path_id=body.path_id,
        course_id=body.course_id,
        topic=body.topic,
        difficulty=body.difficulty,
        task_count=body.task_count,
    )
    cutoff = datetime.now(timezone.utc) - IDEMPOTENCE_WINDOW
    existing_rows = (
        (
            await db.execute(
                select(PathRoom).where(
                    PathRoom.path_id == body.path_id,
                    PathRoom.generation_seed == seed,
                    PathRoom.generated_at.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    fresh: list[PathRoom] = []
    for room in existing_rows:
        generated_at = room.generated_at
        if generated_at is None:
            continue
        # SQLite + aiosqlite returns naive datetimes; treat them as UTC
        # so the cutoff comparison matches the factory's behaviour.
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        if generated_at >= cutoff:
            fresh.append(room)
    if fresh:
        # Newest first — same tie-break as the factory.
        fresh.sort(
            key=lambda r: (
                (
                    r.generated_at.replace(tzinfo=timezone.utc)
                    if r.generated_at is not None and r.generated_at.tzinfo is None
                    else r.generated_at
                )
                or datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True,
        )
        existing = fresh[0]
        return {
            "job_id": None,
            "reused": True,
            "room_id": str(existing.id),
            "path_id": str(existing.path_id),
        }

    # ── Schedule a fresh background job ──
    request_summary = {
        "user_id": str(user.id),
        "path_id": str(body.path_id),
        "course_id": str(body.course_id),
        "topic": body.topic,
        "difficulty": body.difficulty,
        "task_count": body.task_count,
        "generation_seed": seed,
    }
    job_record = await job_store.create_job(request_summary)
    job_id = job_record.job_id

    factory = getattr(request.app.state, "test_session_factory", None) or async_session
    user_id = user.id
    payload_path_id = body.path_id
    payload_course_id = body.course_id
    payload_topic = body.topic
    payload_difficulty = body.difficulty
    payload_task_count = body.task_count

    async def _run() -> None:
        """Run generation in a fresh DB session.

        We never reuse the request's ``db`` session here — by the time
        this coroutine starts, FastAPI has already closed it. Mirrors
        the chat router's ``session_factory`` pattern.
        """

        try:
            await job_store.update_status(job_id, "outline")
            async with factory() as bg_db:
                try:
                    room = await generate_and_persist_room(
                        bg_db,
                        user_id=user_id,
                        path_id=payload_path_id,
                        course_id=payload_course_id,
                        topic=payload_topic,
                        difficulty=payload_difficulty,
                        task_count=payload_task_count,
                    )
                except Exception:
                    # The factory rolls back internally on failure, but
                    # belt-and-braces in case a different error path
                    # leaves the session dirty.
                    await bg_db.rollback()
                    raise
            await job_store.update_status(
                job_id,
                "completed",
                room_id=room.id,
                path_id=room.path_id,
            )
        except Exception as exc:  # noqa: BLE001 — surface every failure
            logger.exception("generate_room job %s failed", job_id)
            await job_store.update_status(
                job_id,
                "error",
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
            )

    asyncio.create_task(_run())

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"job_id": job_id, "reused": False},
    )


# ── Endpoint 6: GET /api/paths/generate-room/stream/{job_id} ──────


@router.get(
    "/generate-room/stream/{job_id}",
    summary="SSE progress stream for a scheduled room-generation job",
    description=(
        "Streams ordered status events for the given ``job_id`` until "
        "the job reaches ``completed`` (final payload includes "
        "``room_id`` + ``path_id``) or ``error`` (final payload "
        "includes ``error_code``)."
    ),
)
async def generate_room_stream(
    job_id: str,
    _user: User = Depends(get_current_user),
):
    """SSE stream of generation progress events for one job."""

    job = await job_store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "job_not_found", "job_id": job_id},
        )

    async def _event_generator():
        async for event in job_store.subscribe(job_id):
            status_value = event.get("status")
            yield {"event": "message", "data": json.dumps(event)}
            if status_value in {"completed", "error"}:
                break

    return EventSourceResponse(_event_generator())


__all__ = ["router"]
