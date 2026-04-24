"""Drills HTTP surface — Phase 16c practice-first pivot.

Five endpoints under ``/api/drills``:

* ``GET  /api/drills/courses``                 — list every compiled course.
* ``GET  /api/drills/courses/{slug}``          — full TOC (modules + drills).
* ``GET  /api/drills/next?course_slug=…``      — next unpassed drill or 204.
* ``GET  /api/drills/{drill_id}``              — single drill detail.
* ``POST /api/drills/{drill_id}/submit``       — run + persist + feedback.

**Route ordering matters.** ``/courses`` and ``/next`` are declared
BEFORE the parameterised ``/{drill_id}`` route so FastAPI matches the
literal path segments instead of coercing them into UUIDs. Same pattern
``routers.paths`` uses for ``/orphans`` before ``/{slug}``; reordering
the decorators breaks those endpoints silently.

``hidden_tests`` is NEVER returned in any response. The schemas in
``schemas/drills.py`` omit the field; any hand-built payload here does
the same. That's the Phase 16c contract — the runner has the tests
server-side, the client only ever sees starter code + hints.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.drill import Drill, DrillCourse, DrillModule
from models.user import User
from schemas.drills import (
    DrillCourseOut,
    DrillCourseTOC,
    DrillModuleTOC,
    DrillOut,
    DrillSubmitRequest,
    DrillSubmitResult,
)
from services.auth.dependency import get_current_user
from services.drill_selector import select_next_drill
from services.drill_submission import NotFoundError, submit_drill


router = APIRouter()


# ── Helpers ─────────────────────────────────────────────────────────


def _drill_to_out(drill: Drill) -> DrillOut:
    """Project a :class:`Drill` ORM row into the wire schema.

    Explicit projection rather than ``DrillOut.model_validate(drill)``
    so the list of fields is audit-visible — if a future migration
    accidentally adds ``hidden_tests`` to the schema we'd see it here
    first.
    """

    return DrillOut(
        id=drill.id,
        slug=drill.slug,
        title=drill.title,
        why_it_matters=drill.why_it_matters,
        starter_code=drill.starter_code,
        hints=list(drill.hints or []),
        skill_tags=list(drill.skill_tags or []),
        source_citation=drill.source_citation,
        time_budget_min=drill.time_budget_min,
        difficulty_layer=drill.difficulty_layer,
        order_index=drill.order_index,
    )


# ── Endpoint 1: GET /api/drills/courses ─────────────────────────────


@router.get(
    "/courses",
    response_model=list[DrillCourseOut],
    summary="List every compiled drill course with module counts",
    description=(
        "Returns one :class:`DrillCourseOut` per ``drill_courses`` row. "
        "``module_count`` is derived via a grouped COUNT so the "
        "dashboard doesn't issue one query per course. Never includes "
        "drill bodies or hidden tests."
    ),
)
async def list_courses(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DrillCourseOut]:
    """Return every course with its module count."""

    courses = list(
        (await db.execute(select(DrillCourse).order_by(DrillCourse.created_at.asc())))
        .scalars()
        .all()
    )
    if not courses:
        return []

    counts = await db.execute(
        select(DrillModule.course_id, func.count(DrillModule.id))
        .where(DrillModule.course_id.in_([c.id for c in courses]))
        .group_by(DrillModule.course_id)
    )
    count_by_course = {row[0]: row[1] for row in counts.all()}

    return [
        DrillCourseOut(
            id=c.id,
            slug=c.slug,
            title=c.title,
            source=c.source,
            version=c.version,
            description=c.description,
            estimated_hours=c.estimated_hours,
            module_count=count_by_course.get(c.id, 0),
        )
        for c in courses
    ]


# ── Endpoint 2: GET /api/drills/courses/{slug} ──────────────────────


@router.get(
    "/courses/{slug}",
    response_model=DrillCourseTOC,
    summary="Full TOC (modules + drills) for one course",
    description=(
        "Returns the course, all its modules in ``order_index`` "
        "ascending, and every module's drills in ``order_index`` "
        "ascending. Hidden tests are stripped via the schema."
    ),
)
async def get_course_toc(
    slug: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DrillCourseTOC:
    """Return the full TOC for one course slug (404 on miss)."""

    course = (
        await db.execute(select(DrillCourse).where(DrillCourse.slug == slug))
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "course_not_found", "slug": slug},
        )

    modules = list(
        (
            await db.execute(
                select(DrillModule)
                .where(DrillModule.course_id == course.id)
                .order_by(DrillModule.order_index.asc())
            )
        )
        .scalars()
        .all()
    )
    module_ids = [m.id for m in modules]

    drills_by_module: dict[uuid.UUID, list[Drill]] = {mid: [] for mid in module_ids}
    if module_ids:
        drill_rows = (
            (
                await db.execute(
                    select(Drill)
                    .where(Drill.module_id.in_(module_ids))
                    .order_by(Drill.module_id, Drill.order_index.asc())
                )
            )
            .scalars()
            .all()
        )
        for drill in drill_rows:
            drills_by_module[drill.module_id].append(drill)

    module_payload = [
        DrillModuleTOC(
            id=m.id,
            slug=m.slug,
            title=m.title,
            order_index=m.order_index,
            outcome=m.outcome,
            drill_count=len(drills_by_module.get(m.id, [])),
            drills=[_drill_to_out(d) for d in drills_by_module.get(m.id, [])],
        )
        for m in modules
    ]

    return DrillCourseTOC(
        id=course.id,
        slug=course.slug,
        title=course.title,
        source=course.source,
        version=course.version,
        description=course.description,
        estimated_hours=course.estimated_hours,
        module_count=len(modules),
        modules=module_payload,
    )


# ── Endpoint 3: GET /api/drills/next ────────────────────────────────
# Declared before ``/{drill_id}`` so FastAPI matches ``next`` as a
# literal segment rather than a UUID path param.


@router.get(
    "/next",
    response_model=Optional[DrillOut],
    summary="Next unpassed drill for the current user within a course",
    description=(
        "Returns the next drill the learner has not yet passed, "
        "iterating modules then drills by ``order_index``. Returns "
        "**204 No Content** when every drill in the course is passed."
    ),
)
async def get_next_drill(
    course_slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Resolve the next drill or 204 if the course is done."""

    nxt = await select_next_drill(db, user.id, course_slug)
    if nxt is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    # Return a typed ``Response`` so the 204 and 200 paths share a
    # return annotation (ty / mypy are happy). FastAPI still validates
    # the 200 payload's shape against ``response_model`` via the OpenAPI
    # schema, but we bypass the auto-serialiser here because it cannot
    # emit a conditional 204.
    payload = _drill_to_out(nxt).model_dump(mode="json")
    return Response(
        content=json.dumps(payload),
        media_type="application/json",
        status_code=status.HTTP_200_OK,
    )


# ── Endpoint 4: GET /api/drills/{drill_id} ──────────────────────────


@router.get(
    "/{drill_id}",
    response_model=DrillOut,
    summary="Single drill detail (no hidden tests)",
    description=(
        "Returns the drill's starter code, hints, and metadata. "
        "``hidden_tests`` is server-only and never present in the "
        "response — it is used exclusively by the runner."
    ),
)
async def get_drill(
    drill_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DrillOut:
    """Return one drill by id (404 on miss)."""

    drill = (
        await db.execute(select(Drill).where(Drill.id == drill_id))
    ).scalar_one_or_none()
    if drill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "drill_not_found", "drill_id": str(drill_id)},
        )
    return _drill_to_out(drill)


# ── Endpoint 5: POST /api/drills/{drill_id}/submit ──────────────────


@router.post(
    "/{drill_id}/submit",
    response_model=DrillSubmitResult,
    summary="Submit a solution; run hidden tests; persist the attempt",
    description=(
        "Runs ``submitted_code`` against the drill's hidden pytest "
        "suite in a sandboxed subprocess (5s timeout), writes a "
        "``drill_attempts`` row regardless of outcome, and returns an "
        "ADHD-safe feedback line. On pass, ``next_drill_id`` is "
        "populated with the next unpassed drill in the same course. "
        "404 on unknown drill id."
    ),
)
async def post_submit(
    drill_id: uuid.UUID,
    payload: DrillSubmitRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DrillSubmitResult:
    """Delegate to :func:`services.drill_submission.submit_drill`."""

    try:
        return await submit_drill(db, user.id, drill_id, payload.submitted_code)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "drill_not_found", "drill_id": str(exc.drill_id)},
        ) from exc


__all__ = ["router"]
