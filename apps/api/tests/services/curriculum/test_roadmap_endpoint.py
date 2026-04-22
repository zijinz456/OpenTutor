"""Unit tests for ``routers.curriculum.get_course_roadmap`` (T3).

Covers the four concerns called out by the T3 techlead brief:

1. **Happy path** — a course with a 3-entry roadmap path, 3 existing
   ``KnowledgeNode`` rows, and 1 ``ConceptMastery`` row for the middle
   node returns 3 entries in path order with mastery ``[0.0, 0.75, 0.0]``
   and ``position`` = ``[0, 1, 2]``.
2. **No roadmap metadata** — a course with ``metadata_`` missing the
   ``roadmap`` key (or with an empty path) returns ``[]``.
3. **Course doesn't exist** — ``get_course_or_404`` raises
   :class:`libs.exceptions.NotFoundError` (status 404), which is exactly
   what the global exception handler in ``main.py`` turns into an HTTP
   404 response.
4. **Deleted node** — if the roadmap path references a node ID that no
   longer exists in ``knowledge_nodes``, that entry is silently omitted
   (no 500, no ghost entry), preserving the positions of surviving nodes.

All tests call the endpoint function directly with stub DB + User, mirroring
``tests/test_canvas_router_unit.py`` (and the T2 test style — pure mocks,
no Postgres / TestClient needed).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from libs.exceptions import NotFoundError
from models.course import Course
from models.knowledge_graph import ConceptMastery, KnowledgeNode
from routers.curriculum import get_course_roadmap


# ── fake infra ──────────────────────────────────────────────


def _user(user_id: uuid.UUID | None = None) -> SimpleNamespace:
    """Minimal ``User``-shaped stub; the endpoint only reads ``.id``."""
    return SimpleNamespace(id=user_id or uuid.uuid4())


def _make_node(
    course_id: uuid.UUID, slug: str, topic: str, blurb: str | None = None
) -> KnowledgeNode:
    return KnowledgeNode(
        id=uuid.uuid4(),
        course_id=course_id,
        name=topic,
        description=blurb,
        metadata_={"source": "syllabus_builder", "slug": slug},
    )


def _mastery(user_id: uuid.UUID, node_id: uuid.UUID, score: float) -> ConceptMastery:
    return ConceptMastery(
        id=uuid.uuid4(),
        user_id=user_id,
        knowledge_node_id=node_id,
        mastery_score=score,
    )


def _make_db_mock(
    course: Course | None,
    join_rows: list[tuple[KnowledgeNode, ConceptMastery | None]] | None = None,
) -> AsyncMock:
    """Build an ``AsyncSession``-shaped mock.

    The endpoint issues at most two queries:

    1. ``select(Course).where(id=course_id, user_id=user_id)`` — resolved
       inside ``get_course_or_404``. Returns ``course`` (or ``None`` → 404).
    2. ``select(KnowledgeNode, ConceptMastery).outerjoin(...).where(...)``
       — the roadmap join. Returns ``join_rows`` (list of
       ``(KnowledgeNode, ConceptMastery|None)`` tuples) via ``.all()``.

    We dispatch by sniffing the compiled SQL fragment, matching the style
    used in ``test_syllabus_persist.py`` so the test is DB-dialect neutral.
    """

    join_rows = join_rows or []

    def _result_for_select_course() -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = course
        return result

    def _result_for_join() -> MagicMock:
        result = MagicMock()
        result.all.return_value = join_rows
        return result

    async def _execute(stmt: Any) -> MagicMock:
        sql = str(stmt).lower()
        if "knowledge_nodes" in sql:
            # The JOIN query references knowledge_nodes; the course lookup
            # does not. Dispatch on that.
            return _result_for_join()
        return _result_for_select_course()

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


# ── tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_roadmap_returns_ordered_entries_with_mastery() -> None:
    """Happy path: 3 nodes in path order, middle one has mastery=0.75."""
    user = _user()
    course_id = uuid.uuid4()

    n1 = _make_node(course_id, "s1", "Basics", "Variables & types.")
    n2 = _make_node(course_id, "s2", "Control Flow", "Conditionals and loops.")
    n3 = _make_node(course_id, "s3", "Functions", "Defining and calling.")

    course = Course(
        id=course_id,
        user_id=user.id,
        name="Python 101",
        metadata_={
            "roadmap": {
                "builder_version": "v2.1",
                "path": [str(n1.id), str(n2.id), str(n3.id)],
                "generated_at": "2026-04-21T00:00:00+00:00",
            }
        },
    )

    mastery_n2 = _mastery(user.id, n2.id, 0.75)
    # Intentionally return join rows in a scrambled order to prove the
    # endpoint re-orders according to path, not DB result order.
    db = _make_db_mock(
        course=course,
        join_rows=[(n3, None), (n1, None), (n2, mastery_n2)],
    )

    entries = await get_course_roadmap(course_id, user=user, db=db)

    assert len(entries) == 3
    assert [e.node_id for e in entries] == [n1.id, n2.id, n3.id]
    assert [e.position for e in entries] == [0, 1, 2]
    assert [e.slug for e in entries] == ["s1", "s2", "s3"]
    assert [e.topic for e in entries] == ["Basics", "Control Flow", "Functions"]
    assert [e.mastery_score for e in entries] == [0.0, 0.75, 0.0]
    assert entries[0].blurb == "Variables & types."


@pytest.mark.asyncio
async def test_roadmap_returns_empty_list_when_no_metadata() -> None:
    """A freshly-created course with no syllabus yet → ``[]`` (not 500)."""
    user = _user()
    course_id = uuid.uuid4()
    course = Course(id=course_id, user_id=user.id, name="Fresh course", metadata_=None)
    db = _make_db_mock(course=course)

    entries = await get_course_roadmap(course_id, user=user, db=db)

    assert entries == []
    # And importantly, no JOIN query should have been issued — we short
    # circuit before hitting knowledge_nodes.
    executed = [str(call.args[0]).lower() for call in db.execute.await_args_list]
    assert not any("knowledge_nodes" in sql for sql in executed)


@pytest.mark.asyncio
async def test_roadmap_returns_empty_list_when_path_is_empty() -> None:
    """``metadata_['roadmap']['path'] == []`` is a valid "no syllabus" state."""
    user = _user()
    course_id = uuid.uuid4()
    course = Course(
        id=course_id,
        user_id=user.id,
        name="Empty path course",
        metadata_={"roadmap": {"builder_version": "v2.1", "path": []}},
    )
    db = _make_db_mock(course=course)

    entries = await get_course_roadmap(course_id, user=user, db=db)

    assert entries == []


@pytest.mark.asyncio
async def test_roadmap_raises_404_when_course_missing() -> None:
    """Missing course → ``NotFoundError`` (status=404), handled globally."""
    user = _user()
    course_id = uuid.uuid4()
    db = _make_db_mock(course=None)

    with pytest.raises(NotFoundError) as excinfo:
        await get_course_roadmap(course_id, user=user, db=db)

    # Sanity: the raised exception maps to HTTP 404 via the global handler.
    assert excinfo.value.status == 404


@pytest.mark.asyncio
async def test_roadmap_skips_missing_nodes_without_500ing() -> None:
    """If the path references a node that's been deleted, that entry is
    omitted. The surviving entries keep their original path positions."""
    user = _user()
    course_id = uuid.uuid4()

    n1 = _make_node(course_id, "s1", "Basics")
    n3 = _make_node(course_id, "s3", "Functions")
    # Middle node ID exists in the path but NOT in the join result — it
    # was deleted sometime after the syllabus was generated.
    missing_id = uuid.uuid4()

    course = Course(
        id=course_id,
        user_id=user.id,
        name="Course with stale path",
        metadata_={
            "roadmap": {
                "builder_version": "v2.1",
                "path": [str(n1.id), str(missing_id), str(n3.id)],
            }
        },
    )
    db = _make_db_mock(course=course, join_rows=[(n1, None), (n3, None)])

    entries = await get_course_roadmap(course_id, user=user, db=db)

    # Only 2 entries (missing one omitted), but the surviving ones keep
    # their original path positions (0 and 2) — the UI can render this as
    # "step 1" and "step 3" so the learner sees that something was culled.
    assert len(entries) == 2
    assert [e.node_id for e in entries] == [n1.id, n3.id]
    assert [e.position for e in entries] == [0, 2]


@pytest.mark.asyncio
async def test_roadmap_tolerates_malformed_path_entries() -> None:
    """A non-UUID string in the path (stale / corrupt metadata) is skipped
    rather than raising ``ValueError`` inside the endpoint."""
    user = _user()
    course_id = uuid.uuid4()

    n1 = _make_node(course_id, "s1", "Basics")
    n2 = _make_node(course_id, "s2", "Next")

    course = Course(
        id=course_id,
        user_id=user.id,
        name="Course with garbage path",
        metadata_={
            "roadmap": {
                "path": [str(n1.id), "not-a-uuid", str(n2.id)],
            }
        },
    )
    db = _make_db_mock(course=course, join_rows=[(n1, None), (n2, None)])

    entries = await get_course_roadmap(course_id, user=user, db=db)

    # Malformed entry dropped; surviving entries keep their original path
    # positions (0 and 2) — same policy as deleted nodes.
    assert len(entries) == 2
    assert [e.node_id for e in entries] == [n1.id, n2.id]
    assert [e.position for e in entries] == [0, 2]
