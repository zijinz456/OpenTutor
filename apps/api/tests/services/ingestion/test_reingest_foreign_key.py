"""Regression tests for the re-ingest FK bug in ``dispatch_content``.

Day-0 bug: POSTing the same URL to a course that already ingested it
failed with ``sqlite3.IntegrityError: FOREIGN KEY constraint failed`` on
the ``DELETE FROM course_content_tree`` inside the dedup branch of
``services.ingestion.dispatch.dispatch_content``. Fresh course + same
URL worked because no prior content_tree rows existed to dedup.

These tests exercise ``dispatch_content`` directly on an isolated
SQLite engine — running the full seven-step ingestion pipeline would
drag in network fetchers, LLM classifiers, embedding jobs, and the
background auto-generation task, none of which are relevant to the FK
path we're hardening.

Note: FK hardening at the DB level (ondelete='SET NULL' via the
20260424_0001 migration) is covered by a manual Postgres smoke test
only — ``Base.metadata.create_all`` on SQLite uses ORM metadata that
reflects the model declarations, which still lack ``ondelete`` on
``practice_problems.content_node_id``. That gap is fine for this
regression: the Python nullify path is what we're asserting works, and
it works precisely because the model-level FK is permissive.
"""

from __future__ import annotations

import os
import tempfile
import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database import Base
from models.content import CourseContentTree
from models.course import Course
from models.ingestion import IngestionJob
from models.practice import PracticeProblem
from models.user import User
from services.ingestion.dispatch import dispatch_content


@pytest_asyncio.fixture
async def db_session(monkeypatch):
    """Per-test SQLite engine with FK enforcement on."""
    fd, db_path = tempfile.mkstemp(prefix="opentutor-reingest-fk-", suffix=".db")
    os.close(fd)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )

    # Enforce FKs on each SQLite connection — without this, SQLite would
    # silently ignore the violation we're trying to test against.
    @sa.event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_connection, _conn_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # dispatch_content spawns background tasks that want ``async_session``
    # from the ``database`` module. Point that at our test factory so the
    # detached tasks either run against the test DB or silently no-op.
    import database as _db_module

    monkeypatch.setattr(_db_module, "async_session", session_factory, raising=True)

    async with session_factory() as session:
        yield session

    await engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


async def _seed_user_and_course(db: AsyncSession, course_name: str = "Test Course"):
    user = User(id=uuid.uuid4(), name="Test")
    course = Course(id=uuid.uuid4(), user_id=user.id, name=course_name)
    db.add_all([user, course])
    await db.flush()
    return user, course


async def _run_dispatch(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    url: str,
    markdown: str,
    original_filename: str,
) -> IngestionJob:
    """Build an ``IngestionJob`` in the state ``dispatch_content`` expects.

    The real pipeline runs classification + extraction upstream; we
    hand-craft an ``IngestionJob`` that mimics what step 5 would hand
    off to step 6.
    """
    job = IngestionJob(
        user_id=user_id,
        source_type="url",
        url=url,
        original_filename=original_filename,
        course_id=course_id,
        content_category="notes",
        classification_method="heuristic",
        status="dispatching",
        extracted_markdown=markdown,
    )
    db.add(job)
    await db.flush()
    await dispatch_content(db, job)
    await db.commit()
    return job


_MARKDOWN = """# Test Article

Some intro paragraph.

## Section One

First section body text.

## Section Two

Second section body text.
"""


@pytest.mark.asyncio
async def test_reingest_same_url_succeeds_on_existing_course(db_session):
    """Re-ingest with a dangling practice_problem reference must not raise.

    This is the exact failure mode from job
    ``17c20c6e-8863-4b49-9142-39b29b8f3468`` on the user's local DB: an
    earlier ingest left practice_problem rows pointing at content_tree
    nodes, and the subsequent re-ingest's DELETE raised
    ``FOREIGN KEY constraint failed``. The dispatch dedup path is the
    unit under test.
    """
    db = db_session
    _, course = await _seed_user_and_course(db)
    course_id = course.id
    user_id = course.user_id
    url = "https://example.com/article"
    filename = url

    # First ingest — lays down the initial content_tree.
    await _run_dispatch(
        db,
        user_id=user_id,
        course_id=course_id,
        url=url,
        markdown=_MARKDOWN,
        original_filename=filename,
    )

    first_rows = (
        (
            await db.execute(
                sa.select(CourseContentTree.id).where(
                    CourseContentTree.course_id == course_id,
                    CourseContentTree.source_file == filename,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(first_rows) >= 1, (
        f"expected at least one content_tree row after first ingest, got {first_rows!r}"
    )

    # Simulate the background auto_generation task: attach a
    # practice_problem to one of the tree nodes, mirroring what
    # ``_safe_auto_generate`` does after the first ingest commits.
    pp = PracticeProblem(
        id=uuid.uuid4(),
        course_id=course_id,
        content_node_id=first_rows[0],
        question_type="mc",
        question="What is this?",
        options={"A": "x", "B": "y"},
        correct_answer="A",
        explanation="because",
        order_index=0,
        source="ai_generated",
        difficulty_layer=1,
    )
    db.add(pp)
    await db.commit()

    # Re-ingest — this is the call that used to crash.
    await _run_dispatch(
        db,
        user_id=user_id,
        course_id=course_id,
        url=url,
        markdown=_MARKDOWN + "\n\nextra trailing edit",
        original_filename=filename,
    )

    # Tree: the old rows are gone; new rows exist under the same source.
    second_rows = (
        (
            await db.execute(
                sa.select(CourseContentTree.id).where(
                    CourseContentTree.course_id == course_id,
                    CourseContentTree.source_file == filename,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(second_rows) >= 1, "re-ingest produced no new content_tree rows"
    assert set(second_rows).isdisjoint(set(first_rows)), (
        "re-ingest kept old row IDs — dedup delete didn't run"
    )

    # practice_problem: survives the delete, but its FK is nullified.
    refreshed = (
        await db.execute(sa.select(PracticeProblem).where(PracticeProblem.id == pp.id))
    ).scalar_one()
    assert refreshed.content_node_id is None, (
        "dispatch dedup should have nullified the practice_problem FK before delete"
    )


@pytest.mark.asyncio
async def test_reingest_does_not_affect_unrelated_course_content(db_session):
    """Dedup must be scoped to ``(course_id, source_file)`` — never spill.

    If a future refactor ever widens the nullify's WHERE clause by
    accident (dropping course_id scoping, say), unrelated courses would
    see their practice_problem FKs nulled out. Pin that here.
    """
    db = db_session
    _, course_a = await _seed_user_and_course(db, course_name="Course A")
    user_id_a = course_a.user_id
    course_a_id = course_a.id
    # Reuse user_a to keep the test simple; what matters is course scoping.
    course_b = Course(id=uuid.uuid4(), user_id=user_id_a, name="Course B")
    db.add(course_b)
    await db.flush()

    url = "https://example.com/shared-title"
    filename = url

    # Seed both courses with the same source URL.
    await _run_dispatch(
        db,
        user_id=user_id_a,
        course_id=course_a_id,
        url=url,
        markdown=_MARKDOWN,
        original_filename=filename,
    )
    await _run_dispatch(
        db,
        user_id=user_id_a,
        course_id=course_b.id,
        url=url,
        markdown=_MARKDOWN,
        original_filename=filename,
    )

    # A practice_problem on each course, each pointing at its own tree.
    tree_a = (
        await db.execute(
            sa.select(CourseContentTree.id).where(
                CourseContentTree.course_id == course_a_id,
                CourseContentTree.source_file == filename,
            )
        )
    ).scalars().first()
    tree_b = (
        await db.execute(
            sa.select(CourseContentTree.id).where(
                CourseContentTree.course_id == course_b.id,
                CourseContentTree.source_file == filename,
            )
        )
    ).scalars().first()
    assert tree_a and tree_b and tree_a != tree_b

    pp_a = PracticeProblem(
        id=uuid.uuid4(),
        course_id=course_a_id,
        content_node_id=tree_a,
        question_type="mc",
        question="A?",
        options={"A": "x"},
        correct_answer="A",
        explanation="a",
        order_index=0,
        source="ai_generated",
        difficulty_layer=1,
    )
    pp_b = PracticeProblem(
        id=uuid.uuid4(),
        course_id=course_b.id,
        content_node_id=tree_b,
        question_type="mc",
        question="B?",
        options={"A": "x"},
        correct_answer="A",
        explanation="b",
        order_index=0,
        source="ai_generated",
        difficulty_layer=1,
    )
    db.add_all([pp_a, pp_b])
    await db.commit()

    # Re-ingest on course A only.
    await _run_dispatch(
        db,
        user_id=user_id_a,
        course_id=course_a_id,
        url=url,
        markdown=_MARKDOWN + "\n\nrevised",
        original_filename=filename,
    )

    # Course B's tree is untouched.
    tree_b_after = (
        (
            await db.execute(
                sa.select(CourseContentTree.id).where(
                    CourseContentTree.course_id == course_b.id,
                    CourseContentTree.source_file == filename,
                )
            )
        )
        .scalars()
        .all()
    )
    assert tree_b in tree_b_after, (
        "course B's content_tree row was deleted by a course A re-ingest — "
        "dedup leaked across courses"
    )

    # Course B's practice_problem FK is intact; course A's was nulled.
    pp_b_after = (
        await db.execute(sa.select(PracticeProblem).where(PracticeProblem.id == pp_b.id))
    ).scalar_one()
    pp_a_after = (
        await db.execute(sa.select(PracticeProblem).where(PracticeProblem.id == pp_a.id))
    ).scalar_one()
    assert pp_b_after.content_node_id == tree_b, (
        f"course B's practice_problem FK changed unexpectedly: {pp_b_after.content_node_id!r}"
    )
    assert pp_a_after.content_node_id is None, (
        "course A's practice_problem FK should have been nulled by dedup"
    )
