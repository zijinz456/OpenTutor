"""Tests for Phase 16a T1 — ``LearningPath`` / ``PathRoom`` ORM and the
``20260423_0003_learning_paths`` Alembic migration.

Covers five T1 merge-criteria:

1. Alembic ``upgrade → downgrade → upgrade`` round-trip leaves the
   ``learning_paths`` + ``path_rooms`` schema consistent.
2. ORM CRUD — a path persists with two ordered rooms.
3. ``ON DELETE CASCADE`` from ``learning_paths`` through ``path_rooms``.
4. Unique slug per path — two rooms with the same slug inside one path
   raise an IntegrityError.
5. ``practice_problems.path_room_id`` stores the FK, and ``SET NULL`` on
   room delete preserves the problem row.

Same test harness as Phase 5 ``test_interview.py``: we invoke the
migration module's ``upgrade``/``downgrade`` through an ``Operations``
context bound to a sync SQLite engine, because the repo's Alembic
``env.py`` short-circuits on SQLite URLs.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import Base
from models.course import Course
from models.learning_path import LearningPath, PathRoom
from models.practice import PracticeProblem
from models.user import User


API_DIR = Path(__file__).resolve().parents[2]
MIGRATION_PATH = API_DIR / "alembic" / "versions" / "20260423_0003_learning_paths.py"

PATH_TABLES = {"learning_paths", "path_rooms"}


# ── helpers ────────────────────────────────────────────────────────────


def _load_migration_module():
    """Import the migration module by file path (it is not on sys.path)."""
    spec = importlib.util.spec_from_file_location(
        "_test_learning_paths_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_engine_with_prereqs(include_path_tables: bool = False):
    """Return a SQLite engine with every pre-existing table created and
    the two Phase 16a tables left for the migration to create.

    When ``include_path_tables`` is True, create all tables including the
    Phase 16a ones — used by the ORM tests that do not exercise the
    migration path directly.
    """
    engine = create_engine("sqlite://", future=True)

    # SQLite needs PRAGMA foreign_keys=ON per-connection for ON DELETE
    # CASCADE and ON DELETE SET NULL to fire. Without this the cascade
    # test would silently pass even when the schema is wrong.
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    if include_path_tables:
        Base.metadata.create_all(engine)
    else:
        prereq_tables = [
            t for t in Base.metadata.sorted_tables if t.name not in PATH_TABLES
        ]
        Base.metadata.create_all(engine, tables=prereq_tables)
    return engine


def _run_migration(engine, direction: str) -> None:
    """Invoke the migration module's ``upgrade`` or ``downgrade`` in a
    real Alembic ``Operations`` context bound to ``engine``.
    """
    assert direction in {"upgrade", "downgrade"}
    module = _load_migration_module()
    with engine.begin() as connection:
        ctx = MigrationContext.configure(connection)
        with Operations.context(ctx):
            getattr(module, direction)()


def _inspect_path_tables(engine) -> dict:
    """Snapshot of the two path tables' metadata via SQLAlchemy inspect."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    state: dict = {"tables": tables & PATH_TABLES}
    if "learning_paths" in tables:
        state["paths_indexes"] = {
            idx["name"] for idx in inspector.get_indexes("learning_paths")
        }
    if "path_rooms" in tables:
        state["rooms_indexes"] = {
            idx["name"] for idx in inspector.get_indexes("path_rooms")
        }
        state["rooms_uniques"] = {
            uc["name"] for uc in inspector.get_unique_constraints("path_rooms")
        }
    return state


# ── 1. Alembic upgrade → downgrade → upgrade round-trip ────────────────


def test_alembic_upgrade_downgrade_roundtrip():
    """Schema survives a full upgrade/downgrade/upgrade cycle intact."""
    engine = _make_engine_with_prereqs(include_path_tables=False)

    # Sanity: neither path table exists yet.
    before = _inspect_path_tables(engine)
    assert before["tables"] == set()

    # First upgrade — both tables + indexes + uniques materialize.
    _run_migration(engine, "upgrade")
    after_up = _inspect_path_tables(engine)
    assert after_up["tables"] == PATH_TABLES
    assert "ix_learning_paths_slug" in after_up["paths_indexes"]
    assert "ix_learning_paths_track_id" in after_up["paths_indexes"]
    assert "ix_path_rooms_path" in after_up["rooms_indexes"]
    assert "uq_path_room_slug_per_path" in after_up["rooms_uniques"]
    assert "uq_path_room_order_per_path" in after_up["rooms_uniques"]

    # Downgrade — both tables and their indexes are dropped.
    _run_migration(engine, "downgrade")
    after_down = _inspect_path_tables(engine)
    assert after_down["tables"] == set()

    # Second upgrade — schema is identical to the first upgrade.
    _run_migration(engine, "upgrade")
    after_up2 = _inspect_path_tables(engine)
    assert after_up2 == after_up


# ── 2. ORM CRUD — path with two rooms, ordered by room_order ───────────


def test_learning_path_orm_crud():
    """Round-trip a ``LearningPath`` with two child rooms."""
    engine = _make_engine_with_prereqs(include_path_tables=True)

    path_id = uuid.uuid4()
    with Session(engine) as db:
        path = LearningPath(
            id=path_id,
            slug="python-fundamentals",
            title="Python Fundamentals",
            difficulty="beginner",
            track_id="python_fundamentals",
            description="From print() to comprehensions.",
            room_count_target=10,
        )
        # Insert rooms out of order on purpose — the relationship must
        # sort them by ``room_order`` on read.
        path.rooms = [
            PathRoom(
                id=uuid.uuid4(),
                path_id=path_id,
                slug="py_loops",
                title="Loops and iteration",
                room_order=1,
                task_count_target=12,
            ),
            PathRoom(
                id=uuid.uuid4(),
                path_id=path_id,
                slug="py_intro",
                title="Variables, numbers, strings",
                room_order=0,
                intro_excerpt="Python is a dynamic language…",
                task_count_target=15,
            ),
        ]
        db.add(path)
        db.commit()

    with Session(engine) as db:
        loaded = db.get(LearningPath, path_id)
        assert loaded is not None
        assert loaded.slug == "python-fundamentals"
        assert loaded.difficulty == "beginner"
        assert loaded.track_id == "python_fundamentals"
        assert loaded.room_count_target == 10

        rooms = loaded.rooms
        assert [r.room_order for r in rooms] == [0, 1]
        assert rooms[0].slug == "py_intro"
        assert rooms[0].intro_excerpt.startswith("Python is a dynamic")
        # Back-reference works.
        assert rooms[0].path.id == path_id


# ── 3. Cascade delete — learning_path → path_rooms ─────────────────────


def test_cascade_delete_path_deletes_rooms():
    """Deleting a learning path removes all of its rooms."""
    engine = _make_engine_with_prereqs(include_path_tables=True)

    path_id = uuid.uuid4()
    room_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

    with Session(engine) as db:
        db.add(
            LearningPath(
                id=path_id,
                slug="python-advanced",
                title="Python Advanced",
                difficulty="advanced",
                track_id="python_advanced",
            )
        )
        db.flush()
        for i, rid in enumerate(room_ids):
            db.add(
                PathRoom(
                    id=rid,
                    path_id=path_id,
                    slug=f"room_{i}",
                    title=f"Room {i}",
                    room_order=i,
                )
            )
        db.commit()

    # Sanity: rooms exist before the cascade.
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM path_rooms")).scalar() == 3

    # Delete the path via raw SQL so SQLite's FK engine, not ORM
    # cascade, is what we're testing.
    with engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM learning_paths WHERE id = :pid"),
            {"pid": str(path_id)},
        )

    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM path_rooms")).scalar() == 0, (
            "path delete should cascade to path_rooms"
        )


# ── 4. Unique slug per path — second room with same slug raises ────────


def test_unique_slug_per_path():
    """Two rooms with identical slug on the same path violate the UC."""
    engine = _make_engine_with_prereqs(include_path_tables=True)

    path_id = uuid.uuid4()
    with Session(engine) as db:
        db.add(
            LearningPath(
                id=path_id,
                slug="python-intermediate",
                title="Python Intermediate",
                difficulty="intermediate",
                track_id="python_intermediate",
            )
        )
        db.flush()
        db.add(
            PathRoom(
                id=uuid.uuid4(),
                path_id=path_id,
                slug="py_intro",
                title="Intro",
                room_order=0,
            )
        )
        db.commit()

    with Session(engine) as db:
        db.add(
            PathRoom(
                id=uuid.uuid4(),
                path_id=path_id,
                # Same slug, different room_order — UC on (path_id, slug)
                # must still reject.
                slug="py_intro",
                title="Duplicate",
                room_order=1,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


# ── 5. practice_problems.path_room_id — column wires + SET NULL ────────


def test_practice_problem_path_room_id_column():
    """A problem's ``path_room_id`` stores the FK and nulls on room delete."""
    engine = _make_engine_with_prereqs(include_path_tables=True)

    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    path_id = uuid.uuid4()
    room_id = uuid.uuid4()
    problem_id = uuid.uuid4()

    with Session(engine) as db:
        db.add(User(id=user_id, name="Path Tester"))
        db.flush()
        db.add(Course(id=course_id, user_id=user_id, name="Python Basics"))
        db.flush()
        db.add(
            LearningPath(
                id=path_id,
                slug="python-practical",
                title="Python Practical",
                difficulty="intermediate",
                track_id="python_practical",
            )
        )
        db.flush()
        db.add(
            PathRoom(
                id=room_id,
                path_id=path_id,
                slug="py_cli",
                title="Building CLIs",
                room_order=0,
            )
        )
        db.flush()
        db.add(
            PracticeProblem(
                id=problem_id,
                course_id=course_id,
                question_type="mc",
                question="Which module parses argv?",
                correct_answer="argparse",
                path_room_id=room_id,
                task_order=0,
            )
        )
        db.commit()

    # Read-back — the FK + task_order round-tripped.
    with Session(engine) as db:
        loaded = db.get(PracticeProblem, problem_id)
        assert loaded is not None
        assert loaded.path_room_id == room_id
        assert loaded.task_order == 0

    # Delete the room via raw SQL to exercise SQLite's FK engine.
    with engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM path_rooms WHERE id = :rid"),
            {"rid": str(room_id)},
        )

    with Session(engine) as db:
        # Problem still exists (no cascade) …
        loaded = db.get(PracticeProblem, problem_id)
        assert loaded is not None, "problem row must survive room delete"
        # … with its FK nulled.
        assert loaded.path_room_id is None
