"""Regression tests for the re-ingest FK bug in ``dispatch_content``.

Day-0 bug (2026-04-24): POSTing the same URL to a course that already
ingested it failed with ``sqlite3.IntegrityError: FOREIGN KEY constraint
failed``. Fresh course + same URL worked because no prior content_tree
rows existed to dedup. The dispatch dedup path tried to DELETE the old
``course_content_tree`` rows without first nullifying the FK from the
legacy ``knowledge_points`` scene-system table, which has no
``ondelete`` clause.

These tests exercise ``dispatch_content`` directly on an isolated
SQLite engine. The production endpoint opens a new ``AsyncSession``
per request via FastAPI DI, so each test here uses a fresh session
per dispatch call to mirror that — using a single long-lived session
would surface SQLAlchemy identity-map staleness that only happens in
tests, not in production.

Note: FK hardening at the DB level (``ondelete='SET NULL'`` via the
``20260424_0001`` migration) is covered by a manual Postgres smoke
test only — ``Base.metadata.create_all`` on SQLite uses ORM metadata
which still lacks ``ondelete`` on ``practice_problems.content_node_id``.
That gap is fine for this regression: we assert the Python nullify
path works end-to-end; the migration hardens fresh installs for the
case where someone bypasses the dispatch code.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from database import Base
from models.content import CourseContentTree
from models.course import Course
from models.ingestion import IngestionJob
from models.practice import PracticeProblem
from models.user import User
from services.ingestion.dispatch import dispatch_content


@pytest_asyncio.fixture
async def engine(monkeypatch) -> AsyncIterator[AsyncEngine]:
    """Per-test SQLite engine with FK enforcement on."""
    fd, db_path = tempfile.mkstemp(prefix="opentutor-reingest-fk-", suffix=".db")
    os.close(fd)

    eng = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )

    # Without this SQLite silently ignores FK violations — the exact
    # opposite of what we're trying to assert against.
    @sa.event.listens_for(eng.sync_engine, "connect")
    def _enable_fk(dbapi_connection, _conn_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        eng, class_=AsyncSession, expire_on_commit=False
    )

    # Some downstream code in dispatch imports ``async_session`` from the
    # ``database`` module to spawn its own sessions for background tasks.
    # Point that at our test factory so those calls still hit the test DB.
    import database as _db_module

    monkeypatch.setattr(_db_module, "async_session", session_factory, raising=True)

    try:
        yield eng
    finally:
        await eng.dispose()
        try:
            os.unlink(db_path)
        except OSError:
            pass


async def _session(engine: AsyncEngine) -> AsyncSession:
    """Open a fresh session bound to ``engine`` — one per logical op.

    Mirrors the FastAPI dep-injection lifecycle (one session per HTTP
    request). Using a single long-lived session in a test causes the
    ORM identity map to serve stale attributes after dispatch's
    Core-level ``UPDATE``/``DELETE``, which isn't a real bug.
    """
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory()


async def _seed_user_and_course(
    engine: AsyncEngine, course_name: str = "Test Course"
) -> tuple[uuid.UUID, uuid.UUID]:
    async with await _session(engine) as db:
        user = User(id=uuid.uuid4(), name="Test")
        course = Course(id=uuid.uuid4(), user_id=user.id, name=course_name)
        db.add_all([user, course])
        await db.commit()
        return user.id, course.id


async def _run_dispatch(
    engine: AsyncEngine,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    url: str,
    markdown: str,
    original_filename: str,
) -> None:
    """Hand-craft the ``IngestionJob`` that step 5 would pass to step 6.

    Uses its own session so the dispatch call runs in the same isolation
    the production ``/api/content/url`` endpoint does — one request,
    one session.
    """
    async with await _session(engine) as db:
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


async def _tree_ids(
    engine: AsyncEngine, course_id: uuid.UUID, source_file: str
) -> list[uuid.UUID]:
    """Read content_tree node ids via raw SQL to sidestep the identity map."""
    async with await _session(engine) as db:
        rows = (
            (
                await db.execute(
                    sa.select(CourseContentTree.id).where(
                        CourseContentTree.course_id == course_id,
                        CourseContentTree.source_file == source_file,
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)


async def _pp_content_node_id(
    engine: AsyncEngine, pp_id: uuid.UUID
) -> uuid.UUID | None:
    """Fresh-session read of one practice_problem's FK value."""
    async with await _session(engine) as db:
        row = (
            await db.execute(
                sa.select(PracticeProblem.content_node_id).where(
                    PracticeProblem.id == pp_id
                )
            )
        ).scalar_one()
        return row


async def _insert_practice_problem(
    engine: AsyncEngine,
    *,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID,
    question: str,
) -> uuid.UUID:
    pp_id = uuid.uuid4()
    async with await _session(engine) as db:
        db.add(
            PracticeProblem(
                id=pp_id,
                course_id=course_id,
                content_node_id=content_node_id,
                question_type="mc",
                question=question,
                options={"A": "x", "B": "y"},
                correct_answer="A",
                explanation="because",
                order_index=0,
                source="ai_generated",
                difficulty_layer=1,
            )
        )
        await db.commit()
    return pp_id


_MARKDOWN = """# Test Article

Some intro paragraph.

## Section One

First section body text.

## Section Two

Second section body text.
"""


@pytest.mark.asyncio
async def test_reingest_same_url_succeeds_on_existing_course(engine):
    """Re-ingest with a dangling practice_problem reference must not raise.

    The production failure mode: an earlier ingest leaves practice_problem
    rows pointing at content_tree nodes, then the subsequent re-ingest's
    dedup-delete raises ``FOREIGN KEY constraint failed``. The dispatch
    dedup path is the unit under test.
    """
    user_id, course_id = await _seed_user_and_course(engine)
    url = "https://example.com/article"
    filename = url

    # First ingest — lays down the initial content_tree.
    await _run_dispatch(
        engine,
        user_id=user_id,
        course_id=course_id,
        url=url,
        markdown=_MARKDOWN,
        original_filename=filename,
    )

    first_rows = await _tree_ids(engine, course_id, filename)
    assert len(first_rows) >= 1, (
        f"expected at least one content_tree row after first ingest, got {first_rows!r}"
    )

    # Simulate the background auto_generation task: attach a
    # practice_problem to one of the tree nodes, mirroring what
    # ``_safe_auto_generate`` does after the first ingest commits.
    pp_id = await _insert_practice_problem(
        engine,
        course_id=course_id,
        content_node_id=first_rows[0],
        question="What is this?",
    )

    # Re-ingest — this is the call that used to crash.
    await _run_dispatch(
        engine,
        user_id=user_id,
        course_id=course_id,
        url=url,
        markdown=_MARKDOWN + "\n\nextra trailing edit",
        original_filename=filename,
    )

    # Tree: the old rows are gone; new rows exist under the same source.
    second_rows = await _tree_ids(engine, course_id, filename)
    assert len(second_rows) >= 1, "re-ingest produced no new content_tree rows"
    assert set(second_rows).isdisjoint(set(first_rows)), (
        "re-ingest kept old row IDs — dedup delete didn't run"
    )

    # practice_problem: survives the delete, but its FK is nullified.
    assert await _pp_content_node_id(engine, pp_id) is None, (
        "dispatch dedup should have nullified the practice_problem FK before delete"
    )


@pytest.mark.asyncio
async def test_reingest_does_not_affect_unrelated_course_content(engine):
    """Dedup must be scoped to ``(course_id, source_file)`` — never spill.

    If a future refactor ever widens the nullify's WHERE clause by
    accident (dropping course_id scoping, say), unrelated courses would
    see their practice_problem FKs nulled out. Pin that here.
    """
    user_id, course_a_id = await _seed_user_and_course(engine, course_name="Course A")

    # Second course owned by the same user — course scoping is what
    # matters for this assertion, not user scoping.
    async with await _session(engine) as db:
        course_b_id = uuid.uuid4()
        db.add(Course(id=course_b_id, user_id=user_id, name="Course B"))
        await db.commit()

    url = "https://example.com/shared-title"
    filename = url

    await _run_dispatch(
        engine,
        user_id=user_id,
        course_id=course_a_id,
        url=url,
        markdown=_MARKDOWN,
        original_filename=filename,
    )
    await _run_dispatch(
        engine,
        user_id=user_id,
        course_id=course_b_id,
        url=url,
        markdown=_MARKDOWN,
        original_filename=filename,
    )

    tree_a_before = await _tree_ids(engine, course_a_id, filename)
    tree_b_before = await _tree_ids(engine, course_b_id, filename)
    assert tree_a_before and tree_b_before
    assert set(tree_a_before).isdisjoint(set(tree_b_before))

    pp_a_id = await _insert_practice_problem(
        engine,
        course_id=course_a_id,
        content_node_id=tree_a_before[0],
        question="A?",
    )
    pp_b_id = await _insert_practice_problem(
        engine,
        course_id=course_b_id,
        content_node_id=tree_b_before[0],
        question="B?",
    )

    # Re-ingest on course A only.
    await _run_dispatch(
        engine,
        user_id=user_id,
        course_id=course_a_id,
        url=url,
        markdown=_MARKDOWN + "\n\nrevised",
        original_filename=filename,
    )

    # Course B's tree is untouched.
    tree_b_after = await _tree_ids(engine, course_b_id, filename)
    assert set(tree_b_before).issubset(set(tree_b_after)), (
        "course B's content_tree rows were deleted by a course A re-ingest — "
        "dedup leaked across courses"
    )

    # Course B's practice_problem FK is intact; course A's was nulled.
    assert await _pp_content_node_id(engine, pp_b_id) == tree_b_before[0], (
        "course B's practice_problem FK changed unexpectedly"
    )
    assert await _pp_content_node_id(engine, pp_a_id) is None, (
        "course A's practice_problem FK should have been nulled by dedup"
    )


@pytest.mark.asyncio
async def test_reingest_nullifies_knowledge_points_fk(engine):
    """Legacy ``knowledge_points`` FK gets nullified before tree delete.

    The bug users actually hit in production: the scene-system table
    ``knowledge_points`` carries an FK to ``course_content_tree.id``
    with no ``ondelete`` clause and no ORM wrapper. Dedup tried to
    DELETE tree rows that still had live references and tripped the
    constraint. There's no ORM model for this table, so we create it
    with raw SQL to mirror the production schema.
    """
    user_id, course_id = await _seed_user_and_course(engine)
    url = "https://example.com/kp"
    filename = url

    async with await _session(engine) as db:
        await db.execute(
            sa.text(
                "CREATE TABLE knowledge_points ("
                "  id TEXT PRIMARY KEY, "
                "  course_id TEXT NOT NULL, "
                "  name TEXT NOT NULL, "
                "  source_content_node_id TEXT, "
                "  FOREIGN KEY(source_content_node_id) "
                "    REFERENCES course_content_tree(id)"
                ")"
            )
        )
        await db.commit()

    await _run_dispatch(
        engine,
        user_id=user_id,
        course_id=course_id,
        url=url,
        markdown=_MARKDOWN,
        original_filename=filename,
    )
    tree_ids = await _tree_ids(engine, course_id, filename)
    assert tree_ids, "first ingest produced no tree rows"

    # Plant a knowledge_points row whose FK would block the dedup-delete
    # unless dispatch nullifies it first.
    kp_id = str(uuid.uuid4())
    async with await _session(engine) as db:
        await db.execute(
            sa.text(
                "INSERT INTO knowledge_points "
                "(id, course_id, name, source_content_node_id) "
                "VALUES (:id, :cid, :n, :src)"
            ),
            {"id": kp_id, "cid": str(course_id), "n": "X", "src": str(tree_ids[0])},
        )
        await db.commit()

    # Re-ingest — used to raise FOREIGN KEY constraint failed here.
    await _run_dispatch(
        engine,
        user_id=user_id,
        course_id=course_id,
        url=url,
        markdown=_MARKDOWN + "\n\nrevised",
        original_filename=filename,
    )

    async with await _session(engine) as db:
        kp_fk = (
            await db.execute(
                sa.text(
                    "SELECT source_content_node_id FROM knowledge_points WHERE id = :id"
                ),
                {"id": kp_id},
            )
        ).scalar_one()
    assert kp_fk is None, (
        "knowledge_points.source_content_node_id should have been nulled by dedup"
    )
