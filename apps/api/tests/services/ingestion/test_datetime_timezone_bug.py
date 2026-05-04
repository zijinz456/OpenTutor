"""Regression tests for naive-vs-aware datetime handling in URL ingestion.

Root cause: ``auto_configure_course()`` compared ``Assignment.due_date`` from
the DB against an aware UTC ``now``. Under SQLite, ``DateTime(timezone=True)``
rows can round-trip back as naive datetimes, which crashed URL ingestion with:

``TypeError: can't compare offset-naive and offset-aware datetimes``

These tests pin the comparison boundary directly so CI does not need Docker or
live network fetches.

The ``due_date`` is computed *relative to ``utcnow()``* rather than being a
hardcoded calendar date — earlier the fixtures used ``2026-04-26`` and broke
silently when wall-clock time crossed past it (the deadline-filter at
``configure.py`` rejects anything ``<= now``, so the welcome-message branch
never fired and the assertion at line 111 went red on every run after that
date). The relative form is also robust to time zone (date math stays in UTC).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from libs.datetime_utils import utcnow
from models.course import Course
from models.ingestion import Assignment
from services.ingestion.auto_generation.configure import auto_configure_course


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = value
    result.scalar_one_or_none.return_value = value
    return result


def _rows_result(rows: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    scalars = MagicMock()
    scalars.all.return_value = rows
    result.scalars.return_value = scalars
    return result


class _DbContext:
    def __init__(self, db: AsyncMock) -> None:
        self._db = db

    async def __aenter__(self) -> AsyncMock:
        return self._db

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def _db_factory_with_due_date(due_date: datetime):
    course_id = uuid.uuid4()
    course = Course(
        id=course_id,
        user_id=uuid.uuid4(),
        name="Timezone Course",
        metadata_={},
    )
    assignment = Assignment(
        course_id=course_id,
        title="Upcoming project",
        due_date=due_date,
        assignment_type="project",
    )

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _rows_result([assignment]),
            _rows_result([("notes", "study design hypothesis testing " * 20)]),
            _scalar_result(5),
            _scalar_result(course),
        ]
    )
    db.commit = AsyncMock()

    return course_id, course, db


def _future_due_date(*, aware: bool) -> datetime:
    """Return a future deadline 5 days out, aware or naive per ``aware``.

    Anchoring to wall-clock keeps the fixture honest: the deadline-filter
    in :func:`auto_configure_course` rejects anything ``<= now``, so a
    hardcoded calendar date silently rots once the year ticks over.
    """

    future = utcnow() + timedelta(days=5)
    return future if aware else future.replace(tzinfo=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "aware"),
    [("naive", False), ("aware", True)],
)
async def test_auto_configure_course_normalizes_due_dates_before_comparison(
    label: str,
    aware: bool,
) -> None:
    """Future deadlines from the DB must be comparable regardless of tzinfo."""
    due_date = _future_due_date(aware=aware)
    course_id, course, db = _db_factory_with_due_date(due_date)

    result = await auto_configure_course(
        lambda: _DbContext(db),
        course_id,
        {"notes": 0, "flashcards": 0, "quiz": 0},
    )

    assert result is not None, label
    assert result["mode_intent"] == "exam_prep_suggest"
    assert "Next deadline: **Upcoming project**" in result["welcome_message"]
    assert course.metadata_["auto_config"]["deadline_count"] == 1
    db.commit.assert_awaited_once()
