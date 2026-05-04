"""Tests for ``scripts.seed_python_foundations`` — Phase A follow-up.

Three things this test file pins down:

1. The seeder uses the real ``User.name`` field (not the ghost
   ``display_name`` it had in the pre-fix revision).
2. Re-seeding with mutated yaml does NOT delete-and-reinsert tasks —
   existing ``PracticeProblem.id`` values are preserved so attached
   ``PracticeResult`` history remains intact.
3. Trimming the yaml (fewer tasks than the DB has) flips the trailing
   rows to ``is_archived=True`` rather than dropping them.

The validator is also exercised on three failure modes (missing
``track``, unknown task type, missing required key for type).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import scripts.seed_python_foundations as seeder
from database import Base
from models.learning_path import LearningPath, PathRoom
from models.practice import PracticeProblem, PracticeResult
from models.user import User
from scripts.seed_python_foundations import (
    CurriculumValidationError,
    _validate_curriculum,
    main,
)


# ── fixtures ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_factory():
    """In-memory SQLite engine sharing one connection across sessions.

    StaticPool keeps ``:memory:`` alive between session opens; the seed
    script's ``async_session`` global is monkeypatched to point at this
    factory in each test.
    """

    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _write_yaml(path: Path, missions: list[dict]) -> Path:
    """Tiny helper — pack ``missions`` into the canonical track wrapper."""

    doc = {
        "track": {
            "slug": "python-foundations-test",
            "title": "Python Foundations (test)",
            "description": "Fixture",
        },
        "missions": missions,
    }
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def patch_async_session(monkeypatch, session_factory):
    """Point ``seeder.async_session`` at the test session factory.

    The script imports ``async_session`` at module load and uses it via
    ``async with async_session() as db`` — monkeypatching the symbol on
    the module reroutes every call to the in-memory engine.
    """

    monkeypatch.setattr(seeder, "async_session", session_factory)
    return session_factory


# ── 1. Validator — happy path ──────────────────────────────────────────


def test_validator_accepts_well_formed_doc():
    """A minimal valid doc (one mission, one mc task) parses cleanly."""

    doc = {
        "track": {"slug": "x", "title": "X"},
        "missions": [
            {
                "slug": "m1",
                "title": "M1",
                "tasks": [
                    {
                        "type": "mc",
                        "prompt": "Q?",
                        "options": {"A": "a", "B": "b"},
                        "correct": "A",
                    }
                ],
            }
        ],
    }
    n_missions, n_tasks = _validate_curriculum(doc)
    assert n_missions == 1
    assert n_tasks == 1


# ── 1b. Validator — failure modes ──────────────────────────────────────


def test_validator_rejects_missing_track():
    with pytest.raises(CurriculumValidationError, match="track"):
        _validate_curriculum({"missions": []})


def test_validator_rejects_unknown_task_type():
    doc = {
        "track": {"slug": "x", "title": "X"},
        "missions": [
            {
                "slug": "m1",
                "title": "M1",
                "tasks": [{"type": "wat", "prompt": "?"}],
            }
        ],
    }
    with pytest.raises(CurriculumValidationError, match="unknown type"):
        _validate_curriculum(doc)


def test_validator_rejects_missing_required_key_with_context():
    """Error message names the mission slug + task index + missing key."""

    doc = {
        "track": {"slug": "x", "title": "X"},
        "missions": [
            {
                "slug": "loops-and-iteration",
                "title": "Loops",
                "tasks": [
                    # mc requires options + correct; this one has neither.
                    {"type": "mc", "prompt": "Q?"},
                ],
            }
        ],
    }
    with pytest.raises(CurriculumValidationError) as exc:
        _validate_curriculum(doc)
    msg = str(exc.value)
    assert "loops-and-iteration" in msg
    assert "task[0]" in msg
    assert "options" in msg or "correct" in msg


# ── 2. validate_only mode does not touch the DB ───────────────────────


@pytest.mark.asyncio
async def test_validate_only_returns_shape_without_db_writes(
    tmp_path, patch_async_session
):
    yaml_path = _write_yaml(
        tmp_path / "course.yaml",
        [
            {
                "slug": "m1",
                "title": "M1",
                "tasks": [
                    {"type": "tf", "prompt": "Q?", "correct": True},
                ],
            }
        ],
    )

    result = await main(str(yaml_path), validate_only=True)
    assert result["validate_only"] is True
    assert result["missions"] == 1
    assert result["tasks"] == 1

    async with patch_async_session() as db:
        # Should be a clean DB — no path/room/problem rows materialized.
        paths = (await db.execute(select(LearningPath))).scalars().all()
        rooms = (await db.execute(select(PathRoom))).scalars().all()
        problems = (await db.execute(select(PracticeProblem))).scalars().all()
        assert paths == []
        assert rooms == []
        assert problems == []


# ── 3. Fresh seed materializes user/course/path/rooms/tasks ────────────


@pytest.mark.asyncio
async def test_fresh_seed_creates_user_with_name_field(tmp_path, patch_async_session):
    """Regression — the seeder used to crash at constructor with
    ``display_name=...``; assert it now writes the User.name field."""

    yaml_path = _write_yaml(
        tmp_path / "course.yaml",
        [
            {
                "slug": "m1",
                "title": "M1",
                "tasks": [
                    {"type": "tf", "prompt": "?", "correct": False},
                ],
            }
        ],
    )

    summary = await main(str(yaml_path))
    assert summary["rooms"] == 1
    assert summary["tasks"] == 1
    assert summary["inserted"] == 1
    assert summary["updated"] == 0
    assert summary["archived"] == 0

    async with patch_async_session() as db:
        users = (await db.execute(select(User))).scalars().all()
        assert len(users) == 1
        assert users[0].name == "Local"
        assert users[0].email == "local@learndopamine.local"


# ── 4. Re-seed preserves PracticeProblem.id (recall history intact) ────


@pytest.mark.asyncio
async def test_reseed_preserves_problem_ids_and_practice_results(
    tmp_path, patch_async_session
):
    """The whole point of the rewrite. Existing rows mutate in place so
    ``PracticeResult.problem_id`` foreign keys keep pointing at the
    right problem after content updates land via re-seed.
    """

    yaml_path = tmp_path / "course.yaml"
    _write_yaml(
        yaml_path,
        [
            {
                "slug": "loops",
                "title": "Loops",
                "tasks": [
                    {
                        "type": "mc",
                        "prompt": "What does range(3) yield?",
                        "options": {"A": "0,1,2", "B": "1,2,3"},
                        "correct": "A",
                    },
                    {"type": "tf", "prompt": "0 is falsy", "correct": True},
                ],
            }
        ],
    )

    # First seed.
    await main(str(yaml_path))

    async with patch_async_session() as db:
        problems = (
            (
                await db.execute(
                    select(PracticeProblem).order_by(PracticeProblem.task_order.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(problems) == 2
        original_id_0 = problems[0].id
        original_id_1 = problems[1].id

        # Stamp a PracticeResult against problem 0 to simulate user history.
        users = (await db.execute(select(User))).scalars().all()
        result_row = PracticeResult(
            id=uuid.uuid4(),
            problem_id=original_id_0,
            user_id=users[0].id,
            user_answer="A",
            is_correct=True,
        )
        db.add(result_row)
        await db.commit()

    # Mutate yaml — rewrite problem 0's prompt + add a third task.
    _write_yaml(
        yaml_path,
        [
            {
                "slug": "loops",
                "title": "Loops",
                "tasks": [
                    {
                        "type": "mc",
                        "prompt": "What does range(3) actually yield?",
                        "options": {"A": "0,1,2", "B": "1,2,3"},
                        "correct": "A",
                    },
                    {"type": "tf", "prompt": "0 is falsy", "correct": True},
                    {
                        "type": "short_answer",
                        "prompt": "Name the keyword for breaking out of a loop.",
                        "accepted_answers": ["break"],
                    },
                ],
            }
        ],
    )

    summary = await main(str(yaml_path))
    assert summary["inserted"] == 1, "third task is new — should be inserted"
    assert summary["updated"] == 2, "first two tasks should mutate in place"
    assert summary["archived"] == 0

    async with patch_async_session() as db:
        problems = (
            (
                await db.execute(
                    select(PracticeProblem)
                    .where(PracticeProblem.is_archived.is_(False))
                    .order_by(PracticeProblem.task_order.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(problems) == 3
        # task_order=0 row keeps its id even though prompt mutated.
        assert problems[0].id == original_id_0
        assert problems[0].question == "What does range(3) actually yield?"
        # task_order=1 row also stable.
        assert problems[1].id == original_id_1
        # task_order=2 is newly inserted; id is fresh.
        assert problems[2].id not in (original_id_0, original_id_1)

        # PracticeResult history still attached to the original problem 0
        # — the FK never dangled because we never deleted.
        results = (await db.execute(select(PracticeResult))).scalars().all()
        assert len(results) == 1
        assert results[0].problem_id == original_id_0


# ── 5. Trim re-seed archives extra rows instead of deleting ────────────


@pytest.mark.asyncio
async def test_reseed_with_fewer_tasks_archives_extras(tmp_path, patch_async_session):
    yaml_path = tmp_path / "course.yaml"
    _write_yaml(
        yaml_path,
        [
            {
                "slug": "trim",
                "title": "Trim",
                "tasks": [
                    {"type": "tf", "prompt": "A", "correct": True},
                    {"type": "tf", "prompt": "B", "correct": False},
                    {"type": "tf", "prompt": "C", "correct": True},
                ],
            }
        ],
    )
    await main(str(yaml_path))

    # Now drop the last task and re-seed.
    _write_yaml(
        yaml_path,
        [
            {
                "slug": "trim",
                "title": "Trim",
                "tasks": [
                    {"type": "tf", "prompt": "A", "correct": True},
                    {"type": "tf", "prompt": "B", "correct": False},
                ],
            }
        ],
    )
    summary = await main(str(yaml_path))
    assert summary["inserted"] == 0
    assert summary["updated"] == 2
    assert summary["archived"] == 1

    async with patch_async_session() as db:
        all_rows = (
            (
                await db.execute(
                    select(PracticeProblem).order_by(PracticeProblem.task_order.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(all_rows) == 3, "row count never shrinks — history is preserved"
        live = [r for r in all_rows if not r.is_archived]
        archived = [r for r in all_rows if r.is_archived]
        assert len(live) == 2
        assert len(archived) == 1
        assert archived[0].task_order == 2
