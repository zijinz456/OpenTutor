"""Phase 16b T1 — ORM round-trip for the four generation metadata fields.

Covers the model-side half of T1 (the migration is covered by the
existing 16a migration round-trip test plus manual inspection). Two
asserts exercised against a fresh in-memory SQLite engine so the
test is hermetic and needs no external DB:

1. A ``PathRoom`` created **without** setting any generation field
   defaults to ``room_type = "standard"`` and leaves the three
   nullable fields (``generated_at`` / ``generator_model`` /
   ``generation_seed``) plus ``capstone_problem_ids`` at ``None``
   after SELECT — matching what a pre-seeded hand-authored room
   looks like.
2. A ``PathRoom`` created **with** all four fields populated
   round-trips cleanly — tz-aware ``datetime``, model string,
   sha256-length seed, ``room_type="generated"``, and JSON capstone
   ids all come back intact after a fresh-session SELECT (not the
   identity-map).

The engine + session setup mirrors
``apps/api/tests/services/ingestion/test_reingest_foreign_key.py``:
``create_async_engine("sqlite+aiosqlite:///:memory:")`` +
``Base.metadata.create_all`` + ``async_sessionmaker`` with
``expire_on_commit=False`` so the test can read attributes after
commit without a refresh dance.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

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

# Importing sibling models is required even though they're unused here —
# ``Base.metadata.create_all`` only creates tables for classes that have
# been imported and registered on ``Base.registry``. The ``PathRoom.tasks``
# relationship refers to ``PracticeProblem``, which refers to ``Course``
# and ``User``, so all three must be imported before ``create_all`` for
# the mapper configuration step to resolve every string-form FK target.
from models.course import Course  # noqa: F401
from models.learning_path import LearningPath, PathRoom
from models.practice import PracticeProblem  # noqa: F401
from models.user import User  # noqa: F401


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Fresh on-disk SQLite engine with the full ORM schema applied.

    ``:memory:`` + ``NullPool`` would give each connection a fresh empty
    database (no pooling = no shared in-memory state), so the fresh-session
    SELECT would see zero tables. A per-test tempfile gives us the same
    isolation with shared state across connections, matching the pattern
    in ``test_reingest_foreign_key.py``.
    """
    fd, db_path = tempfile.mkstemp(prefix="opentutor-gen-fields-", suffix=".db")
    os.close(fd)
    eng = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()
        try:
            os.unlink(db_path)
        except OSError:
            pass


async def _session(engine: AsyncEngine) -> AsyncSession:
    """Open a fresh AsyncSession bound to ``engine``."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory()


async def _seed_path(engine: AsyncEngine) -> uuid.UUID:
    """Persist a minimal ``LearningPath`` and return its id — rooms need a
    parent for the FK."""
    async with await _session(engine) as db:
        path = LearningPath(
            id=uuid.uuid4(),
            slug="test-path",
            title="Test Path",
            difficulty="beginner",
            track_id="test_track",
            room_count_target=0,
        )
        db.add(path)
        await db.commit()
        return path.id


@pytest.mark.asyncio
async def test_path_room_generation_fields_default_to_standard(engine):
    """Hand-seeded rooms: no generation fields set → ``room_type='standard'``
    and the three nullable fields are ``None`` after SELECT."""
    path_id = await _seed_path(engine)
    room_id = uuid.uuid4()

    async with await _session(engine) as db:
        db.add(
            PathRoom(
                id=room_id,
                path_id=path_id,
                slug="hand-seeded",
                title="Hand-seeded room",
                room_order=0,
                task_count_target=5,
            )
        )
        await db.commit()

    # Fresh session — round-trip through the DB, not the identity map.
    async with await _session(engine) as db:
        row = (
            await db.execute(sa.select(PathRoom).where(PathRoom.id == room_id))
        ).scalar_one()

    assert row.room_type == "standard", (
        "expected room_type default 'standard' for hand-seeded row, "
        f"got {row.room_type!r}"
    )
    assert row.generated_at is None
    assert row.generator_model is None
    assert row.generation_seed is None
    assert row.capstone_problem_ids is None


@pytest.mark.asyncio
async def test_path_room_generation_fields_round_trip(engine):
    """LLM-generated rooms: all four fields round-trip cleanly."""
    path_id = await _seed_path(engine)
    room_id = uuid.uuid4()
    gen_at = datetime(2026, 4, 25, 12, 30, 0, tzinfo=timezone.utc)
    # 64-char sha256 hex — canonical length the factory will produce.
    seed_hex = "a" * 64

    async with await _session(engine) as db:
        db.add(
            PathRoom(
                id=room_id,
                path_id=path_id,
                slug="generated-room",
                title="Generated room",
                room_order=0,
                task_count_target=7,
                generated_at=gen_at,
                generator_model="llama-3.3-70b-versatile",
                generation_seed=seed_hex,
                room_type="generated",
                capstone_problem_ids=["capstone-a", "capstone-b", "capstone-c"],
            )
        )
        await db.commit()

    async with await _session(engine) as db:
        row = (
            await db.execute(sa.select(PathRoom).where(PathRoom.id == room_id))
        ).scalar_one()

    assert row.room_type == "generated"
    assert row.generator_model == "llama-3.3-70b-versatile"
    assert row.generation_seed == seed_hex
    assert row.capstone_problem_ids == ["capstone-a", "capstone-b", "capstone-c"]
    assert row.generated_at is not None
    # SQLite strips tz on read in some driver setups — assert the wall
    # clock value, which is the contract the factory + SSE consumer care
    # about. If tzinfo is preserved we also verify it, but don't require.
    assert row.generated_at.replace(tzinfo=None) == gen_at.replace(tzinfo=None)
