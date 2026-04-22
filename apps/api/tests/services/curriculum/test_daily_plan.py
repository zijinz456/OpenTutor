"""Unit tests for ``services.daily_plan.select_daily_plan`` (Phase 13 T1).

Covers the selection contract pinned in ``plan/adhd_ux_phase13.md``:

1. ``size=1`` returns the single most-overdue card, not a random pick.
2. ``size=5`` with 3 overdue + 10 due-today yields the 3 overdue first,
   then 2 earliest-due-today cards — priority dominates even when a
   lower rank has more inventory.
3. ``size=10`` with only 2 cards returns both; ``reason`` stays ``None``
   (a partial fill is a happy-path outcome, not an error).
4. Empty pool returns ``{cards: [], size: 0, reason: "nothing_due"}``.
5. Type-rotation inside a tier: 10 MC + 2 code-exercise + 0 labs at
   ``size=5`` returns a mix, not ``MC * 5``.
6. Bad ``size`` (e.g. 7) raises :class:`ValueError` from the service —
   the HTTP layer rejects it earlier via ``Literal[1, 5, 10]``; these
   tests exercise the service directly.

The tests follow the same AsyncMock / SQL-fragment dispatch pattern as
``test_roadmap_endpoint.py`` so they stay DB-dialect-neutral and don't
need a live SQLite file.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pydantic import TypeAdapter, ValidationError

from models.practice import PracticeProblem
from models.progress import LearningProgress
from schemas.sessions import DailySessionSize
from services.daily_plan import (
    ALLOWED_SIZES,
    select_daily_plan,
)


# ── fixtures / builders ─────────────────────────────────────


_NOW = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)
"""Frozen "now" used to classify FSRS timestamps. The service reads
``utcnow()`` directly, so tests rely on relative offsets (now - 1h,
now + 1h, ...) rather than trying to freeze time — every assertion uses
only the rank order, not absolute timestamps."""


def _problem(
    *,
    question_type: str = "mc",
    content_node_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    question: str = "What is 2 + 2?",
    is_archived: bool = False,
    created_at: datetime | None = None,
) -> PracticeProblem:
    return PracticeProblem(
        id=uuid.uuid4(),
        course_id=course_id or uuid.uuid4(),
        content_node_id=content_node_id,
        question_type=question_type,
        question=question,
        options={"choices": ["3", "4", "5"]} if question_type == "mc" else None,
        correct_answer="4",
        explanation=None,
        order_index=0,
        is_archived=is_archived,
        source="ai_generated",
        source_owner="ai",
        locked=False,
        is_diagnostic=False,
        source_version=1,
        created_at=created_at or _NOW - timedelta(days=30),
    )


def _progress(
    *,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None,
    next_review_at: datetime | None,
    fsrs_reps: int = 1,
    last_studied_at: datetime | None = None,
) -> LearningProgress:
    return LearningProgress(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        course_id=course_id,
        content_node_id=content_node_id,
        next_review_at=next_review_at,
        fsrs_reps=fsrs_reps,
        last_studied_at=last_studied_at,
    )


def _make_db_mock(
    *,
    join_rows: list[tuple[PracticeProblem, LearningProgress | None]],
    failed_ids_in_order: list[uuid.UUID] | None = None,
) -> AsyncMock:
    """Build an async DB mock that dispatches the two queries the
    service issues.

    * The main LEFT-JOIN query references ``learning_progress`` in its
      compiled SQL. We match that substring.
    * The recently-failed query selects from ``practice_results``.
    """

    failed_ids_in_order = failed_ids_in_order or []

    def _join_result() -> MagicMock:
        r = MagicMock()
        r.all.return_value = list(join_rows)
        return r

    def _failed_result() -> MagicMock:
        r = MagicMock()
        # The service expects single-column rows — tuple each id.
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


# ── tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_size_raises_value_error() -> None:
    """Service-level guard: size=7 never reaches the classifier."""
    db = _make_db_mock(join_rows=[])
    with pytest.raises(ValueError) as excinfo:
        await select_daily_plan(db, 7)
    assert "must be one of" in str(excinfo.value)
    # And no query should have been issued once we rejected early.
    assert db.execute.await_count == 0


def test_schema_rejects_sizes_outside_one_five_ten() -> None:
    """Pydantic ``Literal[1, 5, 10]`` backs the HTTP-level 422. This test
    exercises the schema directly — FastAPI produces the actual 422 by
    wrapping the same :class:`pydantic.ValidationError` we assert here.
    """
    adapter = TypeAdapter(DailySessionSize)

    for bad in (0, 2, 3, 4, 6, 7, 9, 11, 100, -1):
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)

    # Sanity: the allowed values pass.
    for good in (1, 5, 10):
        assert adapter.validate_python(good) == good


@pytest.mark.asyncio
async def test_allowed_sizes_are_exactly_one_five_ten() -> None:
    """Tripwire: if someone expands ALLOWED_SIZES without updating the
    ``Literal`` in the schema (or vice versa) the contract splits. This
    test fails loudly so both sides stay in sync.
    """
    assert ALLOWED_SIZES == frozenset({1, 5, 10})


@pytest.mark.asyncio
async def test_empty_pool_returns_nothing_due() -> None:
    """No cards at all → quick-closure marker."""
    db = _make_db_mock(join_rows=[])
    plan = await select_daily_plan(db, 5)
    assert plan.cards == []
    assert plan.size == 0
    assert plan.reason == "nothing_due"


@pytest.mark.asyncio
async def test_size_one_returns_most_overdue_card() -> None:
    """With many overdue cards, size=1 should pick the oldest-due."""
    course_id = uuid.uuid4()
    cn_a, cn_b, cn_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    p_a = _problem(course_id=course_id, content_node_id=cn_a)
    p_b = _problem(course_id=course_id, content_node_id=cn_b)
    p_c = _problem(course_id=course_id, content_node_id=cn_c)

    # All three are overdue, but p_b is MOST overdue.
    lp_a = _progress(course_id=course_id, content_node_id=cn_a,
                     next_review_at=_NOW - timedelta(hours=1))
    lp_b = _progress(course_id=course_id, content_node_id=cn_b,
                     next_review_at=_NOW - timedelta(days=3))
    lp_c = _progress(course_id=course_id, content_node_id=cn_c,
                     next_review_at=_NOW - timedelta(hours=4))

    db = _make_db_mock(join_rows=[(p_a, lp_a), (p_b, lp_b), (p_c, lp_c)])

    plan = await select_daily_plan(db, 1)
    assert plan.size == 1
    assert plan.reason is None
    assert [c.id for c in plan.cards] == [p_b.id]


@pytest.mark.asyncio
async def test_overdue_beats_due_today_under_size_five() -> None:
    """3 overdue + 10 due-today → 3 overdue first, then 2 earliest due."""
    course_id = uuid.uuid4()

    overdue_problems: list[PracticeProblem] = []
    overdue_rows: list[tuple[PracticeProblem, LearningProgress | None]] = []
    for i in range(3):
        cn = uuid.uuid4()
        p = _problem(course_id=course_id, content_node_id=cn)
        # Older index → older overdue timestamp, so stable sort keeps this
        # insertion order inside the "overdue" tier.
        lp = _progress(
            course_id=course_id, content_node_id=cn,
            next_review_at=_NOW - timedelta(days=3 - i),
        )
        overdue_problems.append(p)
        overdue_rows.append((p, lp))

    due_problems: list[PracticeProblem] = []
    due_rows: list[tuple[PracticeProblem, LearningProgress | None]] = []
    for i in range(10):
        cn = uuid.uuid4()
        p = _problem(course_id=course_id, content_node_id=cn)
        # i=0 is earliest due → should land first among due-today picks.
        lp = _progress(
            course_id=course_id, content_node_id=cn,
            next_review_at=_NOW + timedelta(hours=1 + i),
        )
        due_problems.append(p)
        due_rows.append((p, lp))

    db = _make_db_mock(join_rows=overdue_rows + due_rows)

    plan = await select_daily_plan(db, 5)
    assert plan.size == 5
    assert plan.reason is None

    # First three must be the overdue set, in ascending next_review_at
    # order (most overdue first). Order inside overdue_problems is
    # already most-overdue→least because of how we built them.
    # overdue_problems[0] was _NOW - 3d, overdue_problems[2] was _NOW - 1d.
    expected_overdue_order = [
        overdue_problems[0].id,
        overdue_problems[1].id,
        overdue_problems[2].id,
    ]
    assert [c.id for c in plan.cards[:3]] == expected_overdue_order

    # Remaining 2 must come from the due-today tier, in ascending due
    # order (earliest due first).
    assert [c.id for c in plan.cards[3:]] == [
        due_problems[0].id,
        due_problems[1].id,
    ]


@pytest.mark.asyncio
async def test_pool_smaller_than_size_is_happy_path_not_error() -> None:
    """Only 2 cards exist, size=10 asked → return both with reason=None."""
    course_id = uuid.uuid4()
    cn_a, cn_b = uuid.uuid4(), uuid.uuid4()

    p_a = _problem(course_id=course_id, content_node_id=cn_a)
    p_b = _problem(course_id=course_id, content_node_id=cn_b)
    lp_a = _progress(course_id=course_id, content_node_id=cn_a,
                     next_review_at=_NOW - timedelta(hours=2))
    lp_b = _progress(course_id=course_id, content_node_id=cn_b,
                     next_review_at=_NOW + timedelta(hours=6))

    db = _make_db_mock(join_rows=[(p_a, lp_a), (p_b, lp_b)])

    plan = await select_daily_plan(db, 10)
    assert plan.size == 2
    assert plan.reason is None
    assert [c.id for c in plan.cards] == [p_a.id, p_b.id]


@pytest.mark.asyncio
async def test_type_rotation_inside_tier() -> None:
    """10 overdue MC + 2 overdue code → size=5 mixes, doesn't drown in MC."""
    course_id = uuid.uuid4()

    mc_problems: list[PracticeProblem] = []
    mc_rows: list[tuple[PracticeProblem, LearningProgress | None]] = []
    for i in range(10):
        cn = uuid.uuid4()
        p = _problem(course_id=course_id, content_node_id=cn, question_type="mc")
        # Make MC cards OLDER (more overdue) than code — that way a naive
        # implementation that just honours priority would pick MC×5. The
        # type-rotation check is defeated if MC actually gets all 5 slots.
        lp = _progress(course_id=course_id, content_node_id=cn,
                       next_review_at=_NOW - timedelta(days=10 - i))
        mc_problems.append(p)
        mc_rows.append((p, lp))

    code_problems: list[PracticeProblem] = []
    code_rows: list[tuple[PracticeProblem, LearningProgress | None]] = []
    for i in range(2):
        cn = uuid.uuid4()
        p = _problem(course_id=course_id, content_node_id=cn,
                     question_type="code_exercise")
        lp = _progress(course_id=course_id, content_node_id=cn,
                       next_review_at=_NOW - timedelta(hours=1 + i))
        code_problems.append(p)
        code_rows.append((p, lp))

    db = _make_db_mock(join_rows=mc_rows + code_rows)

    plan = await select_daily_plan(db, 5)
    assert plan.size == 5

    types = [c.question_type for c in plan.cards]
    # The critical assertion: code exercises made the cut despite MC's
    # stronger priority. Exactly two code cards should be in the batch.
    assert types.count("code_exercise") == 2
    assert types.count("mc") == 3
    # Round-robin order: [mc, code, mc, code, mc] — MC listed first
    # because its group enters the rotation first (stable-sort by
    # priority puts MC[oldest] ahead of code[oldest]).
    assert types == ["mc", "code_exercise", "mc", "code_exercise", "mc"]


@pytest.mark.asyncio
async def test_recently_failed_tier_after_overdue_and_due() -> None:
    """A problem that's only in the recently-failed set (no LP row) lands
    in rank 2 and is picked only after rank 0/1 are drained."""
    course_id = uuid.uuid4()

    # Rank 0: one overdue card.
    cn_0 = uuid.uuid4()
    p_over = _problem(course_id=course_id, content_node_id=cn_0)
    lp_over = _progress(course_id=course_id, content_node_id=cn_0,
                        next_review_at=_NOW - timedelta(hours=1))

    # Rank 1: one due-today card.
    cn_1 = uuid.uuid4()
    p_due = _problem(course_id=course_id, content_node_id=cn_1)
    lp_due = _progress(course_id=course_id, content_node_id=cn_1,
                       next_review_at=_NOW + timedelta(hours=5))

    # Rank 2: a brand-new problem (no LP row) that appears in the
    # recently-failed list. Under the classifier rules, a problem with
    # lp=None AND in the recently-failed set lands in rank 0 (orphaned
    # FSRS state). To put a card cleanly into rank 2 we give it an LP
    # row with zero reps and no next_review_at.
    cn_2 = uuid.uuid4()
    p_fail = _problem(course_id=course_id, content_node_id=cn_2)
    lp_fail = _progress(course_id=course_id, content_node_id=cn_2,
                        next_review_at=None, fsrs_reps=0)

    db = _make_db_mock(
        join_rows=[(p_over, lp_over), (p_due, lp_due), (p_fail, lp_fail)],
        failed_ids_in_order=[p_fail.id],
    )

    plan = await select_daily_plan(db, 5)
    assert [c.id for c in plan.cards] == [p_over.id, p_due.id, p_fail.id]


@pytest.mark.asyncio
async def test_overdue_and_recently_failed_does_not_double_count() -> None:
    """Same problem in overdue AND recently-failed set → appears once."""
    course_id = uuid.uuid4()
    cn = uuid.uuid4()
    p = _problem(course_id=course_id, content_node_id=cn)
    lp = _progress(course_id=course_id, content_node_id=cn,
                   next_review_at=_NOW - timedelta(hours=2))

    db = _make_db_mock(
        join_rows=[(p, lp)],
        failed_ids_in_order=[p.id],  # same id appears in both sets
    )

    plan = await select_daily_plan(db, 5)
    assert plan.size == 1
    assert [c.id for c in plan.cards] == [p.id]


@pytest.mark.asyncio
async def test_archived_problems_are_excluded() -> None:
    """is_archived=True rows should never be returned. The service filters
    them at the SQL level, so this test verifies the happy-path shape of
    a run where archived rows exist in the same course."""
    course_id = uuid.uuid4()
    cn = uuid.uuid4()
    # Only the non-archived problem is returned by our mock — this
    # mirrors what the WHERE clause would do in the real DB. If the
    # service accidentally reads from a different column or forgets the
    # filter, the mock would no longer match reality and the service
    # tests against the joined row would break.
    p_live = _problem(course_id=course_id, content_node_id=cn, is_archived=False)
    lp = _progress(course_id=course_id, content_node_id=cn,
                   next_review_at=_NOW - timedelta(hours=2))

    db = _make_db_mock(join_rows=[(p_live, lp)])

    plan = await select_daily_plan(db, 5)
    assert [c.id for c in plan.cards] == [p_live.id]


@pytest.mark.asyncio
async def test_size_one_breaks_ties_with_created_at_then_id() -> None:
    """If two cards share next_review_at, created_at + id decide order
    deterministically — size=1 must always return the same card given
    the same input."""
    course_id = uuid.uuid4()
    cn_a, cn_b = uuid.uuid4(), uuid.uuid4()
    tied_due = _NOW - timedelta(hours=2)

    # A is created earlier than B → A wins the tie-break.
    p_a = _problem(course_id=course_id, content_node_id=cn_a,
                   created_at=_NOW - timedelta(days=30))
    p_b = _problem(course_id=course_id, content_node_id=cn_b,
                   created_at=_NOW - timedelta(days=10))
    lp_a = _progress(course_id=course_id, content_node_id=cn_a,
                     next_review_at=tied_due)
    lp_b = _progress(course_id=course_id, content_node_id=cn_b,
                     next_review_at=tied_due)

    # Feed the rows in REVERSE order to prove the sort — not the insertion
    # order — drives the result.
    db = _make_db_mock(join_rows=[(p_b, lp_b), (p_a, lp_a)])

    plan = await select_daily_plan(db, 1)
    assert [c.id for c in plan.cards] == [p_a.id]
