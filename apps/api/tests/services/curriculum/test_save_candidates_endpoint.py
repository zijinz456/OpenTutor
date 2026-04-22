"""Unit tests for ``routers.curriculum.save_flashcard_candidates`` (§14.5 T6).

Path B (dual-write) persistence — every saved candidate lands in BOTH
``practice_problems`` AND ``generated_assets.content['cards']`` so cards
surface immediately in ``GET /api/flashcards/due/{course_id}``.

Covers:
    1. **Happy path** — 2 cards persist to both paths with cross-links.
    2. **Unmatched concept_slug** → ``content_node_id=NULL`` + warning.
    3. **Course not found** → 404 via ``NotFoundError``.
    4. **Empty candidates** → 400 via ``HTTPException``.
    5. **Rollback on mid-flight failure** — partial writes undone.
    6. **Field-contract sweep** — ``source='ai_generated'`` and
       ``spawn_origin='chat_turn'`` appear in BOTH persistence paths.

Style mirrors ``test_roadmap_endpoint.py``: stub DB + User, no Postgres /
TestClient. We build an ``AsyncMock`` that records every ``db.add()``
call so we can introspect the created rows without a live session.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from libs.exceptions import NotFoundError
from models.course import Course
from models.generated_asset import GeneratedAsset
from models.knowledge_graph import KnowledgeNode
from models.practice import PracticeProblem
from routers.curriculum import save_flashcard_candidates
from schemas.curriculum import CardCandidate, SaveCandidatesRequest


# ── fakes ───────────────────────────────────────────────────


def _user(user_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=user_id or uuid.uuid4())


def _make_node(course_id: uuid.UUID, slug: str, name: str = "Topic") -> KnowledgeNode:
    return KnowledgeNode(
        id=uuid.uuid4(),
        course_id=course_id,
        name=name,
        description=None,
        metadata_={"source": "syllabus_builder", "slug": slug},
    )


def _make_db_mock(
    course: Course | None,
    knowledge_nodes: list[KnowledgeNode] | None = None,
    flush_raises_on_call: int | None = None,
) -> AsyncMock:
    """Async-session stub that records ``db.add()`` calls.

    The endpoint issues at most two queries:

    1. ``select(Course).where(id=..., user_id=...)`` in ``get_course_or_404``.
    2. ``select(KnowledgeNode).where(course_id=...)`` for slug resolution
       (only when at least one candidate has a non-empty ``concept_slug``).

    ``db.add(obj)`` is recorded into ``db.added`` so tests can introspect
    what rows the endpoint tried to create.

    ``flush_raises_on_call`` simulates a mid-flight DB failure: if set to
    ``n`` (1-indexed), the ``n``-th ``db.flush()`` call raises
    ``RuntimeError``. Used by the rollback test.
    """

    knowledge_nodes = knowledge_nodes or []

    def _result_for_select_course() -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = course
        return result

    def _result_for_knowledge_nodes() -> MagicMock:
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = knowledge_nodes
        result.scalars.return_value = scalars
        return result

    async def _execute(stmt: Any) -> MagicMock:
        sql = str(stmt).lower()
        if "knowledge_nodes" in sql:
            return _result_for_knowledge_nodes()
        return _result_for_select_course()

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.added: list[Any] = []

    def _add(obj: Any) -> None:
        # Populate PracticeProblem.id on add so later cross-linking works
        # (the real SQLAlchemy flush does this; we simulate it eagerly).
        if isinstance(obj, PracticeProblem) and obj.id is None:
            obj.id = uuid.uuid4()
        db.added.append(obj)

    db.add = MagicMock(side_effect=_add)

    flush_count = {"n": 0}

    async def _flush() -> None:
        flush_count["n"] += 1
        if (
            flush_raises_on_call is not None
            and flush_count["n"] == flush_raises_on_call
        ):
            raise RuntimeError("simulated DB failure on flush")

    db.flush = AsyncMock(side_effect=_flush)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _rows(db: AsyncMock, model: type) -> list[Any]:
    return [obj for obj in db.added if isinstance(obj, model)]


# ── tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_dual_write_with_cross_links() -> None:
    """2 cards → 2 PracticeProblem rows + 1 GeneratedAsset with 2 cards."""
    user = _user()
    course_id = uuid.uuid4()
    course = Course(id=course_id, user_id=user.id, name="C", metadata_=None)
    node = _make_node(course_id, "generators", "Python generators")

    db = _make_db_mock(course=course, knowledge_nodes=[node])

    body = SaveCandidatesRequest(
        candidates=[
            CardCandidate(
                front="What is a Python generator?",
                back="A function using yield to produce values lazily.",
                concept_slug="generators",
            ),
            CardCandidate(
                front="What does GIL stand for?",
                back="Global Interpreter Lock — limits threading in CPython.",
            ),
        ]
    )

    resp = await save_flashcard_candidates(
        course_id=course_id, body=body, user=user, db=db
    )

    # — response shape —
    assert resp.count == 2
    assert len(resp.saved_problem_ids) == 2
    assert resp.warnings == []  # both slugs matched (second was None)

    # — PracticeProblem path —
    pp_rows = _rows(db, PracticeProblem)
    assert len(pp_rows) == 2
    assert [pp.question for pp in pp_rows] == [
        "What is a Python generator?",
        "What does GIL stand for?",
    ]
    assert [pp.correct_answer for pp in pp_rows] == [
        "A function using yield to produce values lazily.",
        "Global Interpreter Lock — limits threading in CPython.",
    ]
    assert all(pp.question_type == "flashcard" for pp in pp_rows)
    assert all(pp.source == "ai_generated" for pp in pp_rows)
    assert all(pp.problem_metadata["spawn_origin"] == "chat_turn" for pp in pp_rows)
    # First card matched the slug → content_node_id set to the node's id.
    assert pp_rows[0].content_node_id == node.id
    # Second card had no slug → content_node_id stays NULL.
    assert pp_rows[1].content_node_id is None

    # — GeneratedAsset path —
    assets = _rows(db, GeneratedAsset)
    assert len(assets) == 1
    asset = assets[0]
    assert asset.asset_type == "flashcards"  # PLURAL — matches /due filter
    assert asset.user_id == user.id
    assert asset.course_id == course_id
    assert asset.id == resp.asset_id

    cards = asset.content["cards"]
    assert len(cards) == 2
    assert [c["front"] for c in cards] == [
        "What is a Python generator?",
        "What does GIL stand for?",
    ]

    # FSRS inline defaults match services.spaced_repetition.flashcards
    # (the /due endpoint treats ``fsrs.due=None`` as always-due).
    for card in cards:
        assert card["fsrs"] == {
            "difficulty": 5.0,
            "stability": 0.0,
            "reps": 0,
            "lapses": 0,
            "state": "new",
            "due": None,
        }

    # — cross-links both ways —
    # PracticeProblem.problem_metadata['asset_id'] → GeneratedAsset.id
    assert all(pp.problem_metadata["asset_id"] == str(asset.id) for pp in pp_rows)
    # GeneratedAsset.content['cards'][i]['practice_problem_id'] → PP.id
    assert [c["practice_problem_id"] for c in cards] == [str(pp.id) for pp in pp_rows]

    # asset-level metadata carries the source markers too
    assert asset.content["metadata"]["source"] == "ai_generated"
    assert asset.content["metadata"]["spawn_origin"] == "chat_turn"

    # Transaction committed, not rolled back.
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_unmatched_concept_slug_yields_null_and_warning() -> None:
    """Unknown slug → content_node_id=NULL + warning in response."""
    user = _user()
    course_id = uuid.uuid4()
    course = Course(id=course_id, user_id=user.id, name="C", metadata_=None)

    # No knowledge nodes at all in this course — slug won't resolve.
    db = _make_db_mock(course=course, knowledge_nodes=[])

    body = SaveCandidatesRequest(
        candidates=[
            CardCandidate(front="Q?", back="A.", concept_slug="nonexistent-topic")
        ]
    )

    resp = await save_flashcard_candidates(
        course_id=course_id, body=body, user=user, db=db
    )

    assert len(resp.warnings) == 1
    assert "nonexistent-topic" in resp.warnings[0]

    pp_rows = _rows(db, PracticeProblem)
    assert len(pp_rows) == 1
    assert pp_rows[0].content_node_id is None  # unmatched → NULL
    assert pp_rows[0].problem_metadata["concept_slug"] == "nonexistent-topic"


@pytest.mark.asyncio
async def test_course_not_found_raises_404() -> None:
    """Missing course → NotFoundError (HTTP 404)."""
    user = _user()
    course_id = uuid.uuid4()
    db = _make_db_mock(course=None)

    body = SaveCandidatesRequest(candidates=[CardCandidate(front="Q?", back="A.")])

    with pytest.raises(NotFoundError) as excinfo:
        await save_flashcard_candidates(
            course_id=course_id, body=body, user=user, db=db
        )

    assert excinfo.value.status == 404
    # We must NOT have attempted any writes before the ownership gate.
    assert db.added == []


@pytest.mark.asyncio
async def test_empty_candidates_rejected_with_400() -> None:
    """Empty batch → HTTP 400. Don't silently save nothing.

    Pydantic ``min_length=1`` rejects the payload before the endpoint
    runs in the HTTP flow, but we also cover the explicit 400 branch by
    calling the endpoint function directly with an empty list. We build
    the request via ``model_construct`` to skip validation (the
    domain-level guard must still fire).
    """
    user = _user()
    course_id = uuid.uuid4()
    course = Course(id=course_id, user_id=user.id, name="C", metadata_=None)
    db = _make_db_mock(course=course)

    # Skip pydantic validation so we exercise the endpoint's own 400 path.
    body = SaveCandidatesRequest.model_construct(candidates=[])

    with pytest.raises(HTTPException) as excinfo:
        await save_flashcard_candidates(
            course_id=course_id, body=body, user=user, db=db
        )

    assert excinfo.value.status_code == 400
    assert "No candidates" in str(excinfo.value.detail)
    # Definitely no writes.
    assert db.added == []


@pytest.mark.asyncio
async def test_rollback_on_midflight_failure() -> None:
    """Second flush raises → rollback fires and commit never happens.

    We simulate a DB failure on the second flush (i.e. the GeneratedAsset
    insert, after PracticeProblem rows were already added). The
    ``try/except`` around the writes must:

      * call ``db.rollback()``
      * NOT call ``db.commit()``
      * propagate the exception so the caller sees the failure
    """
    user = _user()
    course_id = uuid.uuid4()
    course = Course(id=course_id, user_id=user.id, name="C", metadata_=None)
    db = _make_db_mock(course=course, knowledge_nodes=[], flush_raises_on_call=2)

    body = SaveCandidatesRequest(
        candidates=[
            CardCandidate(front="Q1", back="A1"),
            CardCandidate(front="Q2", back="A2"),
        ]
    )

    with pytest.raises(RuntimeError, match="simulated DB failure"):
        await save_flashcard_candidates(
            course_id=course_id, body=body, user=user, db=db
        )

    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_and_spawn_origin_present_in_both_paths() -> None:
    """Field-contract sweep: both persistence paths carry the markers.

    Critic specifically called out that ``source='ai_generated'`` and
    ``spawn_origin='chat_turn'`` must be queryable on BOTH
    ``practice_problems`` AND ``generated_assets`` — not just one.
    """
    user = _user()
    course_id = uuid.uuid4()
    course = Course(id=course_id, user_id=user.id, name="C", metadata_=None)
    db = _make_db_mock(course=course, knowledge_nodes=[])

    body = SaveCandidatesRequest(candidates=[CardCandidate(front="Q?", back="A.")])

    await save_flashcard_candidates(course_id=course_id, body=body, user=user, db=db)

    # PracticeProblem carries both markers in metadata + source column.
    pp = _rows(db, PracticeProblem)[0]
    assert pp.source == "ai_generated"
    assert pp.problem_metadata["spawn_origin"] == "chat_turn"

    # GeneratedAsset carries both markers in content.metadata AND the
    # top-level metadata_ column (for indexable filtering later).
    asset = _rows(db, GeneratedAsset)[0]
    assert asset.content["metadata"]["source"] == "ai_generated"
    assert asset.content["metadata"]["spawn_origin"] == "chat_turn"
    assert asset.metadata_["source"] == "ai_generated"
    assert asset.metadata_["spawn_origin"] == "chat_turn"
