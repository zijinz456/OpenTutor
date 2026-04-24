"""Unit tests for the ADHD Phase 14 T5 bad-day selector."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.daily_plan as daily_plan_module
from models.practice import PracticeProblem
from models.progress import LearningProgress
from services.daily_plan import _EASY_DIFFICULTY_LAYER, select_daily_plan


_NOW = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)


def _problem(
    *,
    question_type: str = "mc",
    difficulty_layer: int | None = _EASY_DIFFICULTY_LAYER,
    content_node_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
    problem_metadata: dict[str, Any] | None = None,
) -> PracticeProblem:
    return PracticeProblem(
        id=uuid.uuid4(),
        course_id=course_id or uuid.uuid4(),
        content_node_id=content_node_id,
        question_type=question_type,
        question="Q?",
        options={"choices": ["a", "b", "c"]} if question_type == "mc" else None,
        correct_answer="a",
        explanation=None,
        order_index=0,
        is_archived=False,
        source="ai_generated",
        source_owner="ai",
        locked=False,
        is_diagnostic=False,
        source_version=1,
        created_at=created_at or (_NOW - timedelta(days=30)),
        difficulty_layer=difficulty_layer,
        problem_metadata=problem_metadata,
    )


def _progress(
    *,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None,
    next_review_at: datetime | None,
) -> LearningProgress:
    return LearningProgress(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        course_id=course_id,
        content_node_id=content_node_id,
        next_review_at=next_review_at,
        fsrs_reps=1,
    )


def _make_db_mock(
    *,
    join_rows: list[tuple[PracticeProblem, LearningProgress | None]],
    failed_ids_in_order: list[uuid.UUID] | None = None,
    hard_fail_ids: list[uuid.UUID] | None = None,
) -> AsyncMock:
    failed_ids_in_order = failed_ids_in_order or []
    hard_fail_ids = hard_fail_ids or []

    def _join_result() -> MagicMock:
        result = MagicMock()
        result.all.return_value = list(join_rows)
        return result

    def _failed_result() -> MagicMock:
        result = MagicMock()
        result.all.return_value = [(pid,) for pid in failed_ids_in_order]
        return result

    def _hard_fail_result() -> MagicMock:
        result = MagicMock()
        result.all.return_value = [(pid,) for pid in hard_fail_ids]
        return result

    async def _execute(stmt: Any) -> MagicMock:
        sql = str(stmt).lower()
        if "having count" in sql:
            return _hard_fail_result()
        if "practice_results" in sql:
            return _failed_result()
        return _join_result()

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


@pytest.fixture(autouse=True)
def _freeze_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daily_plan_module, "utcnow", lambda: _NOW)


@pytest.mark.asyncio
async def test_easy_only_returns_only_easy_layer_cards() -> None:
    course_id = uuid.uuid4()
    easy_node, medium_node = uuid.uuid4(), uuid.uuid4()

    easy_problem = _problem(
        course_id=course_id,
        content_node_id=easy_node,
        difficulty_layer=_EASY_DIFFICULTY_LAYER,
    )
    medium_problem = _problem(
        course_id=course_id,
        content_node_id=medium_node,
        difficulty_layer=2,
    )

    db = _make_db_mock(
        join_rows=[
            (
                easy_problem,
                _progress(
                    course_id=course_id,
                    content_node_id=easy_node,
                    next_review_at=_NOW - timedelta(hours=2),
                ),
            ),
            (
                medium_problem,
                _progress(
                    course_id=course_id,
                    content_node_id=medium_node,
                    next_review_at=_NOW - timedelta(hours=1),
                ),
            ),
        ]
    )

    plan = await select_daily_plan(db, 5, strategy="easy_only")

    assert [card.id for card in plan.cards] == [easy_problem.id]
    assert all(card.difficulty_layer == _EASY_DIFFICULTY_LAYER for card in plan.cards)


@pytest.mark.asyncio
async def test_easy_only_excludes_three_plus_lifetime_wrong_answers() -> None:
    course_id = uuid.uuid4()
    blocked_node, allowed_node = uuid.uuid4(), uuid.uuid4()

    blocked_problem = _problem(course_id=course_id, content_node_id=blocked_node)
    allowed_problem = _problem(course_id=course_id, content_node_id=allowed_node)

    db = _make_db_mock(
        join_rows=[
            (
                blocked_problem,
                _progress(
                    course_id=course_id,
                    content_node_id=blocked_node,
                    next_review_at=_NOW - timedelta(hours=3),
                ),
            ),
            (
                allowed_problem,
                _progress(
                    course_id=course_id,
                    content_node_id=allowed_node,
                    next_review_at=_NOW - timedelta(hours=1),
                ),
            ),
        ],
        hard_fail_ids=[blocked_problem.id],
    )

    plan = await select_daily_plan(db, 5, strategy="easy_only")

    assert [card.id for card in plan.cards] == [allowed_problem.id]


@pytest.mark.asyncio
async def test_easy_only_empty_pool_returns_bad_day_empty_reason() -> None:
    course_id = uuid.uuid4()
    medium_node = uuid.uuid4()
    medium_problem = _problem(
        course_id=course_id,
        content_node_id=medium_node,
        difficulty_layer=2,
    )

    db = _make_db_mock(
        join_rows=[
            (
                medium_problem,
                _progress(
                    course_id=course_id,
                    content_node_id=medium_node,
                    next_review_at=_NOW - timedelta(hours=1),
                ),
            ),
        ]
    )

    plan = await select_daily_plan(db, 5, strategy="easy_only")

    assert plan.cards == []
    assert plan.size == 0
    assert plan.reason == "bad_day_empty"


@pytest.mark.asyncio
async def test_easy_only_preserves_overdue_due_recent_fail_order() -> None:
    course_id = uuid.uuid4()
    overdue_node, due_node, fail_node = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    overdue_problem = _problem(course_id=course_id, content_node_id=overdue_node)
    due_problem = _problem(course_id=course_id, content_node_id=due_node)
    failed_problem = _problem(course_id=course_id, content_node_id=fail_node)

    db = _make_db_mock(
        join_rows=[
            (
                overdue_problem,
                _progress(
                    course_id=course_id,
                    content_node_id=overdue_node,
                    next_review_at=_NOW - timedelta(days=1),
                ),
            ),
            (
                due_problem,
                _progress(
                    course_id=course_id,
                    content_node_id=due_node,
                    next_review_at=_NOW + timedelta(hours=2),
                ),
            ),
            (
                failed_problem,
                _progress(
                    course_id=course_id,
                    content_node_id=fail_node,
                    next_review_at=_NOW + timedelta(days=5),
                ),
            ),
        ],
        failed_ids_in_order=[failed_problem.id],
    )

    plan = await select_daily_plan(db, 5, strategy="easy_only")

    assert [card.id for card in plan.cards] == [
        overdue_problem.id,
        due_problem.id,
        failed_problem.id,
    ]


@pytest.mark.asyncio
async def test_easy_only_preserves_type_rotation() -> None:
    course_id = uuid.uuid4()

    mc1 = _problem(
        course_id=course_id,
        content_node_id=uuid.uuid4(),
        question_type="mc",
        created_at=_NOW - timedelta(days=4),
    )
    mc2 = _problem(
        course_id=course_id,
        content_node_id=uuid.uuid4(),
        question_type="mc",
        created_at=_NOW - timedelta(days=3),
    )
    mc3 = _problem(
        course_id=course_id,
        content_node_id=uuid.uuid4(),
        question_type="mc",
        created_at=_NOW - timedelta(days=2),
    )
    trace = _problem(
        course_id=course_id,
        content_node_id=uuid.uuid4(),
        question_type="trace",
        created_at=_NOW - timedelta(days=1),
    )

    overdue_at = _NOW - timedelta(hours=1)
    db = _make_db_mock(
        join_rows=[
            (
                mc1,
                _progress(
                    course_id=course_id,
                    content_node_id=mc1.content_node_id,
                    next_review_at=overdue_at,
                ),
            ),
            (
                mc2,
                _progress(
                    course_id=course_id,
                    content_node_id=mc2.content_node_id,
                    next_review_at=overdue_at,
                ),
            ),
            (
                mc3,
                _progress(
                    course_id=course_id,
                    content_node_id=mc3.content_node_id,
                    next_review_at=overdue_at,
                ),
            ),
            (
                trace,
                _progress(
                    course_id=course_id,
                    content_node_id=trace.content_node_id,
                    next_review_at=overdue_at,
                ),
            ),
        ]
    )

    plan = await select_daily_plan(db, 5, strategy="easy_only")

    assert [card.question_type for card in plan.cards[:3]] != ["mc", "mc", "mc"]


@pytest.mark.asyncio
async def test_freeze_honored_in_bad_day() -> None:
    course_id = uuid.uuid4()
    frozen = _problem(course_id=course_id, content_node_id=uuid.uuid4())
    available = _problem(course_id=course_id, content_node_id=uuid.uuid4())

    db = _make_db_mock(
        join_rows=[
            (
                frozen,
                _progress(
                    course_id=course_id,
                    content_node_id=frozen.content_node_id,
                    next_review_at=_NOW - timedelta(hours=2),
                ),
            ),
            (
                available,
                _progress(
                    course_id=course_id,
                    content_node_id=available.content_node_id,
                    next_review_at=_NOW - timedelta(hours=1),
                ),
            ),
        ]
    )

    plan = await select_daily_plan(
        db,
        5,
        strategy="easy_only",
        excluded_ids=[frozen.id],
    )

    assert [card.id for card in plan.cards] == [available.id]


@pytest.mark.asyncio
async def test_adhd_safe_regression_unchanged_by_bad_day_filter() -> None:
    course_id = uuid.uuid4()
    medium_problem = _problem(
        course_id=course_id,
        content_node_id=uuid.uuid4(),
        question_type="code_exercise",
        difficulty_layer=3,
    )
    easy_problem = _problem(
        course_id=course_id,
        content_node_id=uuid.uuid4(),
        difficulty_layer=_EASY_DIFFICULTY_LAYER,
    )

    db = _make_db_mock(
        join_rows=[
            (
                medium_problem,
                _progress(
                    course_id=course_id,
                    content_node_id=medium_problem.content_node_id,
                    next_review_at=_NOW - timedelta(hours=3),
                ),
            ),
            (
                easy_problem,
                _progress(
                    course_id=course_id,
                    content_node_id=easy_problem.content_node_id,
                    next_review_at=_NOW - timedelta(hours=1),
                ),
            ),
        ],
        hard_fail_ids=[medium_problem.id],
    )

    plan = await select_daily_plan(db, 5)

    returned_ids = {card.id for card in plan.cards}
    assert medium_problem.id in returned_ids
    assert easy_problem.id in returned_ids
    assert plan.reason is None
