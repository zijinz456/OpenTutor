"""Tests for Phase 5 T1 — ``InterviewSession`` / ``InterviewTurn`` ORM and
the ``20260423_0001_interview_sessions`` Alembic migration.

Covers the three T1 merge-criteria:

1. Alembic ``upgrade → downgrade → upgrade`` round-trip leaves the schema
   consistent (tables + indexes + unique constraint come and go).
2. ORM CRUD — session persists with two child turns, ``turns`` relationship
   returns them ordered by ``turn_number``.
3. ``ON DELETE CASCADE`` from ``users`` propagates through ``interview_sessions``
   to ``interview_turns`` (SQLite requires ``PRAGMA foreign_keys=ON``).

The repo's Alembic ``env.py`` short-circuits on SQLite URLs (schema is
bootstrapped via ``Base.metadata.create_all`` at runtime), so we invoke the
migration module's ``upgrade`` / ``downgrade`` functions directly through an
``Operations`` context bound to a sync engine. This exercises the actual
migration SQL against the same backend the ORM tests use.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session

from database import Base
from models.course import Course
from models.interview import InterviewSession, InterviewTurn
from models.user import User


API_DIR = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    API_DIR / "alembic" / "versions" / "20260423_0001_interview_sessions.py"
)

INTERVIEW_TABLES = {"interview_sessions", "interview_turns"}


# ── helpers ────────────────────────────────────────────────────────────


def _load_migration_module():
    """Import the migration module by file path (it's not on sys.path)."""
    spec = importlib.util.spec_from_file_location(
        "_test_interview_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_engine_with_prereqs():
    """Return a sync SQLite engine with ``users`` + ``courses`` pre-created
    (the two FK targets the migration expects) and FK enforcement enabled.
    """
    engine = create_engine("sqlite://", future=True)

    # SQLite needs PRAGMA foreign_keys=ON per-connection for ON DELETE CASCADE
    # to fire. Without this the cascade test would silently pass even when
    # the schema is wrong.
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Create only the prerequisite tables, NOT interview_* — the migration
    # is responsible for those.
    prereq_tables = [
        t for t in Base.metadata.sorted_tables if t.name not in INTERVIEW_TABLES
    ]
    Base.metadata.create_all(engine, tables=prereq_tables)
    return engine


def _run_migration(engine, direction: str) -> None:
    """Invoke the migration module's ``upgrade`` or ``downgrade`` in a real
    Alembic ``Operations`` context bound to ``engine``.
    """
    assert direction in {"upgrade", "downgrade"}
    module = _load_migration_module()
    with engine.begin() as connection:
        ctx = MigrationContext.configure(connection)
        with Operations.context(ctx):
            getattr(module, direction)()


def _inspect_state(engine) -> dict:
    """Snapshot of the two interview tables' metadata via SQLAlchemy inspect."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    state = {"tables": tables & INTERVIEW_TABLES}
    if "interview_sessions" in tables:
        state["sessions_indexes"] = {
            idx["name"] for idx in inspector.get_indexes("interview_sessions")
        }
    if "interview_turns" in tables:
        state["turns_indexes"] = {
            idx["name"] for idx in inspector.get_indexes("interview_turns")
        }
        state["turns_uniques"] = {
            uc["name"] for uc in inspector.get_unique_constraints("interview_turns")
        }
    return state


# ── 1. Alembic upgrade → downgrade → upgrade round-trip ────────────────


def test_alembic_upgrade_downgrade_roundtrip():
    """Schema survives a full upgrade/downgrade/upgrade cycle intact."""
    engine = _make_engine_with_prereqs()

    # Sanity: neither table exists yet.
    before = _inspect_state(engine)
    assert before["tables"] == set()

    # First upgrade — both tables + indexes + unique constraint materialize.
    _run_migration(engine, "upgrade")
    after_up = _inspect_state(engine)
    assert after_up["tables"] == INTERVIEW_TABLES
    assert "ix_interview_sessions_user_started" in after_up["sessions_indexes"]
    assert "ix_interview_turns_session_turn" in after_up["turns_indexes"]
    assert "uq_interview_turn_session_turn" in after_up["turns_uniques"]

    # Downgrade — both tables and their indexes are dropped.
    _run_migration(engine, "downgrade")
    after_down = _inspect_state(engine)
    assert after_down["tables"] == set()

    # Second upgrade — schema is identical to the first upgrade.
    _run_migration(engine, "upgrade")
    after_up2 = _inspect_state(engine)
    assert after_up2 == after_up


# ── 2. ORM CRUD — session + two turns via relationship ─────────────────


def test_interview_session_orm_crud():
    """Round-trip an ``InterviewSession`` with two child turns."""
    engine = _make_engine_with_prereqs()
    _run_migration(engine, "upgrade")

    user_id = uuid.uuid4()
    session_id = uuid.uuid4()

    with Session(engine) as db:
        db.add(User(id=user_id, name="Interview Tester"))
        db.flush()

        session_row = InterviewSession(
            id=session_id,
            user_id=user_id,
            mode="mixed",
            duration="quick",
            project_focus="3ddepo-search",
            total_turns=3,
        )
        session_row.turns = [
            InterviewTurn(
                id=uuid.uuid4(),
                session_id=session_id,
                turn_number=1,
                question_type="behavioral",
                question="Walk me through why you picked FAISS flat IP.",
                answer="Because the corpus is small.",
                rubric_scores_json={
                    "situation": 3,
                    "task": 4,
                    "action": 4,
                    "result": 3,
                },
                grounding_source="star_stories.md#story-2",
            ),
            InterviewTurn(
                id=uuid.uuid4(),
                session_id=session_id,
                turn_number=2,
                question_type="technical",
                question="What's the tradeoff vs HNSW?",
                answer=None,
            ),
        ]
        db.add(session_row)
        db.commit()

    with Session(engine) as db:
        loaded = db.get(InterviewSession, session_id)
        assert loaded is not None
        assert loaded.mode == "mixed"
        assert loaded.duration == "quick"
        assert loaded.total_turns == 3
        # Server default propagated.
        assert loaded.completed_turns == 0
        assert loaded.status == "in_progress"

        # Relationship loads the two turns, ordered by ``turn_number``.
        turns = loaded.turns
        assert [t.turn_number for t in turns] == [1, 2]
        assert turns[0].rubric_scores_json["situation"] == 3
        assert turns[1].answer is None
        # Back-reference works.
        assert turns[0].session.id == session_id


# ── 3. Cascade delete — user → sessions → turns ────────────────────────


def test_cascade_delete_user_cascades_session_and_turns():
    """Deleting a user removes its interview_sessions and their turns."""
    engine = _make_engine_with_prereqs()
    _run_migration(engine, "upgrade")

    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    turn_ids = [uuid.uuid4(), uuid.uuid4()]

    with Session(engine) as db:
        db.add(User(id=user_id, name="Cascade Tester"))
        db.flush()
        db.add(
            InterviewSession(
                id=session_id,
                user_id=user_id,
                mode="behavioral",
                duration="quick",
                project_focus="3ddepo-search",
                total_turns=2,
            )
        )
        db.flush()
        for i, tid in enumerate(turn_ids, start=1):
            db.add(
                InterviewTurn(
                    id=tid,
                    session_id=session_id,
                    turn_number=i,
                    question_type="behavioral",
                    question=f"Q{i}",
                )
            )
        db.commit()

    # Sanity: rows exist before the cascade.
    with engine.connect() as conn:
        assert (
            conn.execute(sa.text("SELECT COUNT(*) FROM interview_sessions")).scalar()
            == 1
        )
        assert (
            conn.execute(sa.text("SELECT COUNT(*) FROM interview_turns")).scalar() == 2
        )

    # Delete the user via raw SQL so SQLite's FK engine, not ORM cascade,
    # is what we're testing.
    with engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM users WHERE id = :uid"), {"uid": str(user_id)}
        )

    with engine.connect() as conn:
        assert (
            conn.execute(sa.text("SELECT COUNT(*) FROM interview_sessions")).scalar()
            == 0
        ), "user delete should cascade to interview_sessions"
        assert (
            conn.execute(sa.text("SELECT COUNT(*) FROM interview_turns")).scalar() == 0
        ), "session delete should cascade to interview_turns"


# ── 4. course_id ON DELETE SET NULL — asymmetric to user cascade ───────


def test_course_delete_sets_session_course_id_null():
    """Dropping a course must null the session's ``course_id`` but keep the row.

    This guards the ``ondelete="SET NULL"`` choice for the course FK — the
    interview history should survive a course deletion.
    """
    engine = _make_engine_with_prereqs()
    _run_migration(engine, "upgrade")

    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    session_id = uuid.uuid4()

    with Session(engine) as db:
        db.add(User(id=user_id, name="Course Tester"))
        db.flush()
        db.add(Course(id=course_id, user_id=user_id, name="Test Course"))
        db.flush()
        db.add(
            InterviewSession(
                id=session_id,
                user_id=user_id,
                course_id=course_id,
                mode="technical",
                duration="standard",
                project_focus="coursera-rag",
                total_turns=10,
            )
        )
        db.commit()

    with engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM courses WHERE id = :cid"), {"cid": str(course_id)}
        )

    with Session(engine) as db:
        # Session row must still exist …
        loaded = db.get(InterviewSession, session_id)
        assert loaded is not None, "session must survive course delete"
        # … with course_id nulled by the FK.
        assert loaded.course_id is None
