import uuid
from datetime import datetime, timezone

import pytest

from models.course import Course
from models.ingestion import Assignment
from services.scraper.canvas_parser import _upsert_assignment, _upsert_course


class _FakeResult:
    def __init__(self, scalar):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeDB:
    def __init__(self, scalars):
        self._scalars = list(scalars)
        self.added = []
        self.flushed = 0

    async def execute(self, _stmt):
        scalar = self._scalars.pop(0) if self._scalars else None
        return _FakeResult(scalar)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1


@pytest.mark.asyncio
async def test_upsert_course_updates_existing_description():
    existing = Course(
        user_id=uuid.uuid4(),
        name="CS101",
        description="old",
        metadata_={"source": "other"},
    )
    db = _FakeDB([existing])

    status = await _upsert_course(db, existing.user_id, "CS101", "new")

    assert status == "updated"
    assert existing.description == "new"
    assert existing.metadata_["source"] == "canvas_scrape"


@pytest.mark.asyncio
async def test_upsert_assignment_updates_due_date_and_metadata():
    course_id = uuid.uuid4()
    existing = Assignment(
        course_id=course_id,
        title="HW1",
        due_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        assignment_type="homework",
        metadata_json={"source": "canvas_scrape", "points": "10"},
    )
    db = _FakeDB([existing])
    new_due = datetime(2026, 1, 2, tzinfo=timezone.utc)

    status = await _upsert_assignment(
        db,
        course_id=course_id,
        title="HW1",
        due_date=new_due,
        assignment_type="homework",
        metadata={"points": "20"},
    )

    assert status == "updated"
    assert existing.due_date == new_due
    assert existing.metadata_json["points"] == "20"
