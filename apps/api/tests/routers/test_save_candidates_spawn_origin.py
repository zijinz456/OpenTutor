"""Phase 4 T3 — ``save-candidates`` accepts ``spawn_origin`` + ``screenshot_hash``.

Covers the three Phase 4 Task T3 acceptance criteria:

1. **Default behaviour** — a request body without ``spawn_origin`` still
   persists ``"chat_turn"`` into both ``practice_problems.problem_metadata``
   and ``generated_assets`` (backward-compat for existing §14.5 clients).
2. **Screenshot origin** — ``spawn_origin="screenshot"`` + per-card
   ``screenshot_hash`` land on both persistence paths; ``problem_metadata``
   carries the hash under ``"screenshot_hash"`` for the audit trail.
3. **Validation** — an unknown ``spawn_origin`` value is rejected at the
   Pydantic layer (FastAPI responds 422; the Pydantic ``Literal`` guard
   raises ``ValidationError`` directly when constructed in-process).

Test shape mirrors ``tests/services/curriculum/test_save_candidates_endpoint.py``:
stub async DB, no Postgres / TestClient required. We introspect
``db.add(...)`` to assert the written metadata shape.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from models.course import Course
from models.generated_asset import GeneratedAsset
from models.practice import PracticeProblem
from routers.curriculum import save_flashcard_candidates
from schemas.curriculum import CardCandidate, SaveCandidatesRequest


# ── fakes (mirrors test_save_candidates_endpoint.py) ────────


def _user(user_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=user_id or uuid.uuid4())


def _make_db_mock(course: Course | None) -> AsyncMock:
    """Async-session stub that records ``db.add()`` rows for introspection.

    Simplified cut of the fixture in ``test_save_candidates_endpoint.py``:
    no knowledge-node lookup branch (our candidates omit ``concept_slug``)
    and no mid-flight flush-failure simulation.
    """

    def _result_for_select_course() -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = course
        return result

    def _result_for_knowledge_nodes() -> MagicMock:
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
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


# ── tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_candidates_defaults_to_chat_turn() -> None:
    """No ``spawn_origin`` in body → default ``"chat_turn"`` preserved.

    Backward-compat guarantee: existing §14.5 clients that never sent
    ``spawn_origin`` must continue to produce the same metadata payload.
    """
    user = _user()
    course_id = uuid.uuid4()
    course = Course(id=course_id, user_id=user.id, name="C", metadata_=None)
    db = _make_db_mock(course=course)

    # No ``spawn_origin`` field — must fall back to the Literal default.
    body = SaveCandidatesRequest(
        candidates=[CardCandidate(front="Q?", back="A.")],
    )
    assert body.spawn_origin == "chat_turn"

    await save_flashcard_candidates(course_id=course_id, body=body, user=user, db=db)

    pp = _rows(db, PracticeProblem)[0]
    assert pp.problem_metadata["spawn_origin"] == "chat_turn"
    # No screenshot_hash key leaks onto chat-turn rows (the key is only
    # added when the candidate actually carries one).
    assert "screenshot_hash" not in pp.problem_metadata

    asset = _rows(db, GeneratedAsset)[0]
    assert asset.content["metadata"]["spawn_origin"] == "chat_turn"
    assert asset.metadata_["spawn_origin"] == "chat_turn"


@pytest.mark.asyncio
async def test_save_candidates_screenshot_origin() -> None:
    """``spawn_origin="screenshot"`` + ``screenshot_hash`` → both paths tagged.

    Phase 4 screenshot-to-drill writes must land in the same save-candidates
    endpoint with the origin and per-card hash propagated into
    ``problem_metadata`` and ``generated_assets``.
    """
    user = _user()
    course_id = uuid.uuid4()
    course = Course(id=course_id, user_id=user.id, name="C", metadata_=None)
    db = _make_db_mock(course=course)

    body = SaveCandidatesRequest(
        candidates=[
            CardCandidate(
                front="What does the screenshot show?",
                back="A Python traceback with AttributeError on NoneType.",
                screenshot_hash="a1b2c3d4e5f67890",
            ),
        ],
        spawn_origin="screenshot",
    )

    await save_flashcard_candidates(course_id=course_id, body=body, user=user, db=db)

    # — practice_problems.problem_metadata —
    pp = _rows(db, PracticeProblem)[0]
    assert pp.problem_metadata["spawn_origin"] == "screenshot"
    assert pp.problem_metadata["screenshot_hash"] == "a1b2c3d4e5f67890"

    # — generated_assets: both content.metadata AND metadata_ column —
    asset = _rows(db, GeneratedAsset)[0]
    assert asset.content["metadata"]["spawn_origin"] == "screenshot"
    assert asset.metadata_["spawn_origin"] == "screenshot"


@pytest.mark.asyncio
async def test_save_candidates_interview_origin_with_session_id() -> None:
    """Phase 5 T5: ``spawn_origin="interview"`` + ``interview_session_id``
    round-trip into BOTH ``problem_metadata`` and ``generated_assets``.

    The interview flow hands its spawned cards to the same
    ``save_flashcard_candidates`` path that §14.5 and Phase 4 use — the
    audit fields distinguish them downstream (drill-again analytics,
    per-session reports).
    """
    user = _user()
    course_id = uuid.uuid4()
    interview_session_id = uuid.uuid4()
    course = Course(id=course_id, user_id=user.id, name="C", metadata_=None)
    db = _make_db_mock(course=course)

    body = SaveCandidatesRequest(
        candidates=[
            CardCandidate(
                front="Revisit: why FAISS flat IP over HNSW?",
                back="Answer lacked p95 latency numbers and build-time tradeoff.",
            ),
        ],
        spawn_origin="interview",
        interview_session_id=interview_session_id,
    )

    await save_flashcard_candidates(course_id=course_id, body=body, user=user, db=db)

    pp = _rows(db, PracticeProblem)[0]
    assert pp.problem_metadata["spawn_origin"] == "interview"
    assert pp.problem_metadata["interview_session_id"] == str(interview_session_id)

    asset = _rows(db, GeneratedAsset)[0]
    assert asset.content["metadata"]["spawn_origin"] == "interview"
    assert asset.metadata_["spawn_origin"] == "interview"


def test_save_candidates_rejects_invalid_spawn_origin() -> None:
    """Unknown ``spawn_origin`` → Pydantic ``ValidationError`` → 422 in HTTP.

    ``Literal["chat_turn", "screenshot"]`` lets Pydantic guard the field
    before our endpoint ever runs; FastAPI returns 422 to the client.
    We assert the underlying validation layer here (no HTTP roundtrip
    needed — the guard is purely schema-driven).
    """
    with pytest.raises(ValidationError) as excinfo:
        SaveCandidatesRequest(
            candidates=[CardCandidate(front="Q?", back="A.")],
            spawn_origin="invalid_value",  # type: ignore[arg-type]
        )
    # Error message references the offending field.
    assert "spawn_origin" in str(excinfo.value)
