"""Unit + small integration tests for ``services.drill_loader`` (Phase 16c T5).

The loader has three responsibilities we care about:

1. **Shape validation** — malformed YAML aborts with a readable error
   BEFORE touching the DB (fast, subprocess-free).
2. **Idempotent upsert** — same slugs produce the same rows; changed
   fields overwrite (fast, subprocess-free).
3. **Reference-solution gate** — every drill's canonical answer must
   pass its own hidden tests (subprocess, slow — one case only).

Upsert helpers are exercised directly against a fresh in-memory SQLite
DB (fast). The full ``load_course`` happy path is covered by one
subprocess-backed test against a tiny inline fixture.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database import Base

# Import the models package so every ORM table is registered with
# ``Base.metadata`` before ``create_all``. Otherwise only the tables
# referenced in this file's explicit imports would be created.
import models  # noqa: F401
from models.drill import Drill, DrillCourse, DrillModule
from services import drill_loader
from services.drill_loader import (
    _upsert_course,
    _upsert_drill,
    _upsert_module,
    _validate_yaml,
    load_course,
)


# ── Fixture harness ─────────────────────────────────────────────────


@pytest_asyncio.fixture
async def in_memory_session():
    """Fresh on-disk SQLite per test.

    A file path (not ``:memory:``) is used because in-memory SQLite is
    per-connection — ``create_all`` and the session would land on
    different empty DBs otherwise. The fixture name is kept for
    readability; the underlying DB is ephemeral either way.
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-drill-loader-", suffix=".db")
    os.close(fd)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        yield session
    await engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


def _drill_doc(slug: str = "drill-1", order: int = 1) -> dict:
    """Build a minimal valid drill doc (no subprocess gate — for upsert tests)."""

    return {
        "slug": slug,
        "title": "Drill",
        "why_it_matters": "reason",
        "starter_code": "def f():\n    ...\n",
        "hidden_tests": "def test_stub():\n    assert True\n",
        "reference_solution": "def f():\n    return 1\n",
        "hints": ["hint"],
        "skill_tags": ["tag"],
        "source_citation": "cite",
        "time_budget_min": 5,
        "difficulty_layer": 1,
        "order_index": order,
    }


def _module_doc(
    slug: str = "mod-1", order: int = 1, drills: list | None = None
) -> dict:
    return {
        "slug": slug,
        "title": "Module",
        "order_index": order,
        "drills": drills or [_drill_doc()],
    }


def _course_doc(modules: list | None = None) -> dict:
    return {
        "slug": "test-course",
        "title": "Test Course",
        "source": "test",
        "version": "v1.0.0",
        "description": "desc",
        "estimated_hours": 3,
        "modules": modules or [_module_doc()],
    }


# ── Shape validation ────────────────────────────────────────────────


def test_validate_yaml_rejects_non_mapping_root():
    # Deliberately pass a non-mapping to prove the guard fires. ``cast``
    # silences the static type check for this single call — the runtime
    # path still sees a ``str`` and raises ``ValueError``.
    from typing import Any, cast

    with pytest.raises(ValueError, match="root must be a mapping"):
        _validate_yaml(cast("dict[str, Any]", "just a string"))


def test_validate_yaml_requires_top_level_keys():
    with pytest.raises(ValueError, match="missing top-level key"):
        _validate_yaml({"slug": "x"})


def test_validate_yaml_requires_non_empty_modules():
    with pytest.raises(ValueError, match="non-empty list"):
        _validate_yaml({**_course_doc(), "modules": []})


def test_validate_yaml_rejects_duplicate_module_slug():
    doc = _course_doc(
        modules=[_module_doc(slug="dup", order=1), _module_doc(slug="dup", order=2)]
    )
    with pytest.raises(ValueError, match="duplicate module slug"):
        _validate_yaml(doc)


def test_validate_yaml_rejects_missing_drill_keys():
    bad_drill = _drill_doc()
    del bad_drill["hidden_tests"]
    doc = _course_doc(modules=[_module_doc(drills=[bad_drill])])
    with pytest.raises(ValueError, match="missing keys"):
        _validate_yaml(doc)


def test_validate_yaml_rejects_out_of_range_difficulty():
    bad = _drill_doc()
    bad["difficulty_layer"] = 4
    doc = _course_doc(modules=[_module_doc(drills=[bad])])
    with pytest.raises(ValueError, match="difficulty_layer must be 1/2/3"):
        _validate_yaml(doc)


def test_validate_yaml_accepts_minimum_valid_doc():
    """A minimal well-formed doc passes without raising."""

    _validate_yaml(_course_doc())


# ── Upsert helpers (fast, no subprocess) ────────────────────────────


@pytest.mark.asyncio
async def test_upsert_course_insert_then_update(in_memory_session: AsyncSession):
    """First call inserts; second call on same slug mutates in place."""

    doc = _course_doc()
    course1 = await _upsert_course(in_memory_session, doc)
    course1_id = course1.id
    assert course1.title == "Test Course"

    doc["title"] = "Renamed"
    doc["estimated_hours"] = 9
    course2 = await _upsert_course(in_memory_session, doc)

    assert course2.id == course1_id
    assert course2.title == "Renamed"
    assert course2.estimated_hours == 9


@pytest.mark.asyncio
async def test_upsert_drill_stores_all_fields_except_reference_solution(
    in_memory_session: AsyncSession,
):
    """``reference_solution`` is never persisted (critic C3)."""

    course = await _upsert_course(in_memory_session, _course_doc())
    module = await _upsert_module(in_memory_session, course.id, _module_doc())
    drill = await _upsert_drill(in_memory_session, module.id, _drill_doc())
    await in_memory_session.flush()

    # Reload from DB to be sure it's persisted, not just attribute-set.
    fresh = (
        await in_memory_session.execute(select(Drill).where(Drill.id == drill.id))
    ).scalar_one()

    assert fresh.hidden_tests.startswith("def test_stub")
    assert fresh.difficulty_layer == 1
    assert fresh.time_budget_min == 5
    assert fresh.hints == ["hint"]
    assert fresh.skill_tags == ["tag"]
    # Reference_solution has no column — can't exist on the ORM row.
    assert not hasattr(fresh, "reference_solution")


@pytest.mark.asyncio
async def test_upsert_module_updates_drills_by_slug_not_duplicating(
    in_memory_session: AsyncSession,
):
    """Re-upserting the same (module, drill slug) mutates, doesn't duplicate."""

    course = await _upsert_course(in_memory_session, _course_doc())
    module = await _upsert_module(in_memory_session, course.id, _module_doc())

    await _upsert_drill(in_memory_session, module.id, _drill_doc(slug="d1", order=1))
    # Same slug, new title
    updated_doc = _drill_doc(slug="d1", order=1)
    updated_doc["title"] = "Renamed Drill"
    await _upsert_drill(in_memory_session, module.id, updated_doc)
    await in_memory_session.flush()

    rows = (
        (
            await in_memory_session.execute(
                select(Drill).where(Drill.module_id == module.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].title == "Renamed Drill"


# ── Full load_course (slow path — subprocess reference-solution gate) ─


@pytest.mark.asyncio
async def test_load_course_end_to_end_against_fixture(
    tmp_path: Path, in_memory_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """``load_course`` reads YAML, validates refsol via subprocess, upserts.

    One-drill fixture keeps subprocess count to 1 (~400ms on Windows).
    We monkeypatch ``_locate_course_yaml`` rather than scaffolding the
    repo-root directory walk — keeps the test hermetic.
    """

    fixture_path = tmp_path / "content" / "drills" / "testc" / "v1.0.0" / "course.yaml"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "slug": "testc",
        "title": "Test Course",
        "source": "test",
        "version": "v1.0.0",
        "description": "ephemeral",
        "estimated_hours": 1,
        "modules": [
            {
                "slug": "m1",
                "title": "Module 1",
                "order_index": 1,
                "drills": [
                    {
                        "slug": "d1",
                        "title": "Sum two ints",
                        "why_it_matters": "Practice small functions.",
                        "starter_code": "def add(a, b):\n    ...\n",
                        "hidden_tests": (
                            "from solution import add\n\n"
                            "def test_sum():\n"
                            "    assert add(2, 3) == 5\n"
                        ),
                        "reference_solution": "def add(a, b):\n    return a + b\n",
                        "hints": ["Return a + b."],
                        "skill_tags": ["functions"],
                        "source_citation": "unit test",
                        "time_budget_min": 2,
                        "difficulty_layer": 1,
                        "order_index": 1,
                    }
                ],
            }
        ],
    }
    fixture_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    def _locate_stub(slug: str, version: str) -> Path:
        assert slug == "testc"
        assert version == "v1.0.0"
        return fixture_path

    monkeypatch.setattr(drill_loader, "_locate_course_yaml", _locate_stub)

    course = await load_course(in_memory_session, "testc", "v1.0.0")
    await in_memory_session.commit()

    assert course.slug == "testc"
    modules = (
        (
            await in_memory_session.execute(
                select(DrillModule).where(DrillModule.course_id == course.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(modules) == 1
    drills = (
        (
            await in_memory_session.execute(
                select(Drill).where(Drill.module_id == modules[0].id)
            )
        )
        .scalars()
        .all()
    )
    assert len(drills) == 1
    assert drills[0].slug == "d1"


@pytest.mark.asyncio
async def test_load_course_rejects_refsol_that_fails_its_own_tests(
    tmp_path: Path, in_memory_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """A drill whose reference_solution fails its hidden_tests aborts cleanly."""

    fixture_path = tmp_path / "course.yaml"
    doc = {
        "slug": "bad",
        "title": "Bad",
        "source": "test",
        "version": "v1.0.0",
        "modules": [
            {
                "slug": "m1",
                "title": "M1",
                "order_index": 1,
                "drills": [
                    {
                        "slug": "d1",
                        "title": "t",
                        "why_it_matters": "x",
                        "starter_code": "def f():\n    ...\n",
                        "hidden_tests": (
                            "from solution import f\n\n"
                            "def test():\n    assert f() == 1\n"
                        ),
                        # Returns 0 — will fail "assert f() == 1"
                        "reference_solution": "def f():\n    return 0\n",
                        "hints": [],
                        "skill_tags": [],
                        "source_citation": "t",
                        "time_budget_min": 1,
                        "difficulty_layer": 1,
                        "order_index": 1,
                    }
                ],
            }
        ],
    }
    fixture_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    monkeypatch.setattr(drill_loader, "_locate_course_yaml", lambda s, v: fixture_path)

    with pytest.raises(ValueError, match="reference_solution does not pass"):
        await load_course(in_memory_session, "bad", "v1.0.0")

    # Confirm nothing was written (the refsol gate runs before upsert)
    rows = (await in_memory_session.execute(select(DrillCourse))).scalars().all()
    assert rows == []


# Silence an unused-import warning when this file is imported but uuid
# isn't used in a specific test path; explicit reference keeps ruff happy.
_ = uuid
