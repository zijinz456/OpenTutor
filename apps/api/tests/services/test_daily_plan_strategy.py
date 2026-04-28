"""Unit tests for ``services.daily_plan.select_daily_plan`` strategy kwarg
+ ``services.brutal_plan.select_brutal_plan`` (Phase 6 T1).

Covers:

* ``strategy="struggle_first"`` swaps tier ranks — recent-fail first,
  then overdue, then due-today, then rank 3 never-seen-with-concept_slug.
* Struggle-first filters out code_exercise / lab_exercise rows (MC-only).
* Struggle-first allows sizes {20, 30, 50}; rejects ADHD sizes {1, 5, 10}.
* ADHD-safe strategy is UNCHANGED — size=5 with a mixed pool still works
  the Phase 13 way (regression guard).
* ``select_brutal_plan`` returns ``warning="pool_small"`` when the pool
  could not fill the requested size.
* Empty pool → ``reason="nothing_due"`` with no ``pool_small`` warning
  (distinguishes "nothing to drill" from "partial fill").

Follows the same AsyncMock dispatch pattern as
``tests/services/curriculum/test_daily_plan.py`` — no live DB.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.practice import PracticeProblem
from models.progress import LearningProgress
from services.brutal_plan import select_brutal_plan
from services.daily_plan import (
    ALLOWED_BRUTAL_SIZES,
    ALLOWED_SIZES,
    select_daily_plan,
)


_NOW = datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)


def _problem(
    *,
    question_type: str = "mc",
    content_node_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    problem_metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
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
        created_at=created_at or _NOW - timedelta(days=30),
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
) -> AsyncMock:
    failed_ids_in_order = failed_ids_in_order or []

    def _join_result() -> MagicMock:
        r = MagicMock()
        r.all.return_value = list(join_rows)
        return r

    def _failed_result() -> MagicMock:
        r = MagicMock()
        r.all.return_value = [(pid,) for pid in failed_ids_in_order]
        return r

    async def _execute(stmt: Any) -> MagicMock:
        sql = str(stmt).lower()
        if "practice_results" in sql:
            return _failed_result()
        return _join_result()

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


# ── strategy contract tests ──────────────────────────────────


@pytest.mark.asyncio
async def test_struggle_first_rank_zero_is_recent_fail() -> None:
    """Under struggle_first the recently-failed card leads the batch,
    even if older overdue cards exist."""
    course_id = uuid.uuid4()
    cn_fail, cn_overdue, cn_due = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    p_fail = _problem(course_id=course_id, content_node_id=cn_fail)
    p_overdue = _problem(course_id=course_id, content_node_id=cn_overdue)
    p_due = _problem(course_id=course_id, content_node_id=cn_due)

    # recently-failed: next_review beyond due_horizon (now + 24h) so it
    # skips tier_overdue AND tier_due_today, landing in tier_recent_fail.
    lp_fail = _progress(
        course_id=course_id,
        content_node_id=cn_fail,
        next_review_at=_NOW + timedelta(days=5),
    )
    lp_overdue = _progress(
        course_id=course_id,
        content_node_id=cn_overdue,
        next_review_at=_NOW - timedelta(days=3),
    )
    lp_due = _progress(
        course_id=course_id,
        content_node_id=cn_due,
        next_review_at=_NOW + timedelta(hours=2),
    )

    db = _make_db_mock(
        join_rows=[(p_fail, lp_fail), (p_overdue, lp_overdue), (p_due, lp_due)],
        failed_ids_in_order=[p_fail.id],  # marks p_fail as recent-fail
    )

    # Pin ``now`` to the test anchor so ``next_review_at`` offsets land
    # in the intended tier regardless of wall-clock drift between when
    # the test was authored and when it runs (the test's ``next_review_at
    # = _NOW + timedelta(days=5)`` must end up beyond ``due_horizon``).
    plan = await select_daily_plan(db, 20, strategy="struggle_first", now=_NOW)
    assert plan.size >= 1
    # The recent-fail card must come before the overdue card.
    ids = [c.id for c in plan.cards]
    assert p_fail.id in ids
    assert p_overdue.id in ids
    assert ids.index(p_fail.id) < ids.index(p_overdue.id)


@pytest.mark.asyncio
async def test_struggle_first_filters_code_and_lab_types() -> None:
    """Struggle-first MC-only: code_exercise / lab_exercise rows are
    dropped even when they're overdue."""
    course_id = uuid.uuid4()
    cn_mc, cn_code, cn_lab = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    p_mc = _problem(course_id=course_id, content_node_id=cn_mc, question_type="mc")
    p_code = _problem(
        course_id=course_id, content_node_id=cn_code, question_type="code_exercise"
    )
    p_lab = _problem(
        course_id=course_id, content_node_id=cn_lab, question_type="lab_exercise"
    )

    lp_mc = _progress(
        course_id=course_id,
        content_node_id=cn_mc,
        next_review_at=_NOW - timedelta(hours=1),
    )
    lp_code = _progress(
        course_id=course_id,
        content_node_id=cn_code,
        next_review_at=_NOW - timedelta(hours=2),
    )
    lp_lab = _progress(
        course_id=course_id,
        content_node_id=cn_lab,
        next_review_at=_NOW - timedelta(hours=3),
    )

    db = _make_db_mock(join_rows=[(p_mc, lp_mc), (p_code, lp_code), (p_lab, lp_lab)])

    plan = await select_daily_plan(db, 20, strategy="struggle_first")
    ids = [c.id for c in plan.cards]
    assert p_mc.id in ids
    assert p_code.id not in ids
    assert p_lab.id not in ids
    assert all(c.question_type == "mc" for c in plan.cards)


@pytest.mark.asyncio
async def test_struggle_first_invalid_size_raises() -> None:
    """Size=7 (ADHD size) rejected under struggle_first."""
    db = _make_db_mock(join_rows=[])
    with pytest.raises(ValueError):
        await select_daily_plan(db, 7, strategy="struggle_first")


@pytest.mark.asyncio
async def test_adhd_safe_unchanged_regression() -> None:
    """Phase 13 size=5 behavior preserved — ADHD default still accepts
    code_exercise rows and does not reject on small pool."""
    course_id = uuid.uuid4()
    cn_mc, cn_code = uuid.uuid4(), uuid.uuid4()
    p_mc = _problem(course_id=course_id, content_node_id=cn_mc, question_type="mc")
    p_code = _problem(
        course_id=course_id, content_node_id=cn_code, question_type="code_exercise"
    )
    lp_mc = _progress(
        course_id=course_id,
        content_node_id=cn_mc,
        next_review_at=_NOW - timedelta(hours=1),
    )
    lp_code = _progress(
        course_id=course_id,
        content_node_id=cn_code,
        next_review_at=_NOW - timedelta(hours=2),
    )

    db = _make_db_mock(join_rows=[(p_mc, lp_mc), (p_code, lp_code)])

    # Default strategy (adhd_safe) keeps code_exercise
    plan = await select_daily_plan(db, 5)  # no strategy kwarg → default
    types = {c.question_type for c in plan.cards}
    assert "mc" in types
    assert "code_exercise" in types


@pytest.mark.asyncio
async def test_brutal_allowed_sizes_are_exactly_20_30_50() -> None:
    """Tripwire: Literal ↔ constant consistency."""
    assert ALLOWED_BRUTAL_SIZES == frozenset({20, 30, 50})
    assert ALLOWED_SIZES.isdisjoint(ALLOWED_BRUTAL_SIZES)


# ── brutal_plan wrapper contract tests ───────────────────────


@pytest.mark.asyncio
async def test_brutal_plan_pool_small_warning() -> None:
    """Pool < requested → warning='pool_small'."""
    course_id = uuid.uuid4()
    cn = uuid.uuid4()
    p = _problem(course_id=course_id, content_node_id=cn)
    lp = _progress(
        course_id=course_id,
        content_node_id=cn,
        next_review_at=_NOW - timedelta(hours=1),
    )

    # 1-card pool, requested 20
    db = _make_db_mock(join_rows=[(p, lp)])

    plan, warning = await select_brutal_plan(db, size=20)
    assert len(plan.cards) == 1
    assert warning == "pool_small"


@pytest.mark.asyncio
async def test_brutal_plan_empty_pool_no_warning() -> None:
    """Empty pool → reason='nothing_due', warning=None (not pool_small)."""
    db = _make_db_mock(join_rows=[])

    plan, warning = await select_brutal_plan(db, size=30)
    assert plan.cards == []
    assert plan.reason == "nothing_due"
    assert warning is None


@pytest.mark.asyncio
async def test_brutal_plan_full_fill_no_warning() -> None:
    """Pool >= requested → warning=None."""
    course_id = uuid.uuid4()
    join_rows: list[tuple[PracticeProblem, LearningProgress | None]] = []
    for _ in range(25):
        cn = uuid.uuid4()
        p = _problem(course_id=course_id, content_node_id=cn)
        lp = _progress(
            course_id=course_id,
            content_node_id=cn,
            next_review_at=_NOW - timedelta(hours=1),
        )
        join_rows.append((p, lp))

    db = _make_db_mock(join_rows=join_rows)

    plan, warning = await select_brutal_plan(db, size=20)
    assert len(plan.cards) == 20
    assert warning is None
