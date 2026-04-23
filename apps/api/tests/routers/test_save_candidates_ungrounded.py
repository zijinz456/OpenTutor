"""Phase 4 T6 — ``save-candidates`` writes ``ungrounded`` flag for screenshot batches.

Covers the four T6 acceptance criteria:

1. **Matching slug** — screenshot card whose ``concept_slug`` resolves to an
   existing ``KnowledgeNode`` in the course → ``problem_metadata.ungrounded``
   is ``False``.
2. **Unknown slug** — screenshot card whose ``concept_slug`` does not match
   any ``KnowledgeNode`` → ``ungrounded`` is ``True``.
3. **No slug** — screenshot card with ``concept_slug=None`` → ``ungrounded``
   is ``True`` (missing slug is treated as ungrounded by construction).
4. **Backward-compat** — ``spawn_origin="chat_turn"`` (default) → the
   ``ungrounded`` key is NEVER added to ``problem_metadata``, so existing
   §14.5 tests and clients see the exact same metadata shape.

Test shape mirrors ``test_save_candidates_spawn_origin.py``: stub async DB,
no Postgres / TestClient required. We introspect ``db.add(...)`` to assert
the written metadata shape.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.course import Course
from models.knowledge_graph import KnowledgeNode
from models.practice import PracticeProblem
from routers.curriculum import save_flashcard_candidates
from schemas.curriculum import CardCandidate, SaveCandidatesRequest


# ── fakes ────────────────────────────────────────────────────


def _user(user_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=user_id or uuid.uuid4())


def _make_db_mock(
    course: Course | None,
    knowledge_nodes: list[KnowledgeNode] | None = None,
) -> AsyncMock:
    """Async-session stub that records ``db.add()`` rows for introspection.

    Accepts an optional ``knowledge_nodes`` list so a test can stage the
    course's ``KnowledgeNode`` rows that the slug-resolver pulls via
    ``select(KnowledgeNode).where(course_id=...)``.
    """

    nodes = knowledge_nodes or []

    def _result_for_select_course() -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = course
        return result

    def _result_for_knowledge_nodes() -> MagicMock:
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = nodes
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
        # Populate PracticeProblem.id eagerly so asset cross-links resolve.
        if isinstance(obj, PracticeProblem) and obj.id is None:
            obj.id = uuid.uuid4()
        db.added.append(obj)

    db.add = MagicMock(side_effect=_add)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _rows(db: AsyncMock, model: type) -> list[Any]:
    return [obj for obj in db.added if isinstance(obj, model)]


def _node(course_id: uuid.UUID, slug: str, name: str = "Node") -> KnowledgeNode:
    """Build a KnowledgeNode instance with a slug in metadata_."""
    return KnowledgeNode(
        id=uuid.uuid4(),
        course_id=course_id,
        name=name,
        description=None,
        metadata_={"slug": slug, "source": "auto_extracted"},
    )


# ── tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_screenshot_card_with_matching_slug_ungrounded_false() -> None:
    """Slug matches an existing ``KnowledgeNode`` → ``ungrounded=False``."""
    user = _user()
    course_id = uuid.uuid4()
    course = Course(id=course_id, user_id=user.id, name="C", metadata_=None)
    node = _node(course_id, slug="race-condition", name="Race Condition")
    db = _make_db_mock(course=course, knowledge_nodes=[node])

    body = SaveCandidatesRequest(
        candidates=[
            CardCandidate(
                front="What is a race condition?",
                back="Two threads touching shared state without sync.",
                concept_slug="race-condition",
            ),
        ],
        spawn_origin="screenshot",
    )

    await save_flashcard_candidates(course_id=course_id, body=body, user=user, db=db)

    pp = _rows(db, PracticeProblem)[0]
    assert pp.problem_metadata["ungrounded"] is False
    assert pp.problem_metadata["spawn_origin"] == "screenshot"


@pytest.mark.asyncio
async def test_screenshot_card_with_unknown_slug_ungrounded_true() -> None:
    """Slug does not resolve to any ``KnowledgeNode`` → ``ungrounded=True``."""
    user = _user()
    course_id = uuid.uuid4()
    course = Course(id=course_id, user_id=user.id, name="C", metadata_=None)
    # Course has no matching node (or zero nodes — either way slug misses).
    db = _make_db_mock(course=course, knowledge_nodes=[])

    body = SaveCandidatesRequest(
        candidates=[
            CardCandidate(
                front="Q?",
                back="A.",
                concept_slug="nonexistent-xyz",
            ),
        ],
        spawn_origin="screenshot",
    )

    await save_flashcard_candidates(course_id=course_id, body=body, user=user, db=db)

    pp = _rows(db, PracticeProblem)[0]
    assert pp.problem_metadata["ungrounded"] is True


@pytest.mark.asyncio
async def test_screenshot_card_with_no_slug_ungrounded_true() -> None:
    """Missing ``concept_slug`` on a screenshot card → ``ungrounded=True``."""
    user = _user()
    course_id = uuid.uuid4()
    course = Course(id=course_id, user_id=user.id, name="C", metadata_=None)
    db = _make_db_mock(course=course, knowledge_nodes=[])

    body = SaveCandidatesRequest(
        candidates=[
            CardCandidate(front="Q?", back="A.", concept_slug=None),
        ],
        spawn_origin="screenshot",
    )

    await save_flashcard_candidates(course_id=course_id, body=body, user=user, db=db)

    pp = _rows(db, PracticeProblem)[0]
    assert pp.problem_metadata["ungrounded"] is True


@pytest.mark.asyncio
async def test_chat_turn_card_no_ungrounded_field() -> None:
    """Default ``spawn_origin="chat_turn"`` → ``ungrounded`` key absent.

    Backward-compat: §14.5 chat-turn rows must keep the exact metadata
    shape they had before Phase 4 T6. Only screenshot-origin batches
    carry the new flag.
    """
    user = _user()
    course_id = uuid.uuid4()
    course = Course(id=course_id, user_id=user.id, name="C", metadata_=None)
    db = _make_db_mock(course=course, knowledge_nodes=[])

    body = SaveCandidatesRequest(
        candidates=[CardCandidate(front="Q?", back="A.")],
        # spawn_origin omitted → defaults to "chat_turn"
    )
    assert body.spawn_origin == "chat_turn"

    await save_flashcard_candidates(course_id=course_id, body=body, user=user, db=db)

    pp = _rows(db, PracticeProblem)[0]
    assert "ungrounded" not in pp.problem_metadata
