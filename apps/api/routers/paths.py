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

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.learning_path import LearningPath, PathRoom
from models.practice import PracticeProblem
from models.user import User
from services.auth.dependency import get_current_user
from services.learning_paths import (
    count_orphan_cards,
    get_completed_task_ids,
    get_room_task_counts,
    sample_orphan_cards,
)

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
    """Payload for ``GET /api/paths/{slug}/rooms/{room_id}``."""

    id: uuid.UUID
    slug: str
    title: str
    room_order: int
    intro_excerpt: Optional[str] = None
    path_id: uuid.UUID
    path_slug: str
    path_title: str
    tasks: list[RoomTask]
    task_total: int = Field(..., ge=0)
    task_complete: int = Field(..., ge=0)


class OrphanSample(BaseModel):
    """One entry in ``OrphanListResponse.sample``."""

    id: str
    title: str


class OrphanListResponse(BaseModel):
    """Payload for ``GET /api/paths/orphans``."""

    count: int = Field(..., ge=0)
    sample: list[OrphanSample]


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

    return RoomDetailResponse(
        id=room.id,
        slug=room.slug,
        title=room.title,
        room_order=room.room_order,
        intro_excerpt=room.intro_excerpt,
        path_id=path.id,
        path_slug=path.slug,
        path_title=path.title,
        tasks=payload,
        task_total=task_total,
        task_complete=task_complete,
    )


__all__ = ["router"]
