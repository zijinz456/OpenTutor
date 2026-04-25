"""End-to-end integration test for the drill flow (Phase 16c GATE-1 glue).

Until now each drill-layer service (loader, selector, submission) had its
own unit test against a hand-seeded DB. This module wires them together
the way a real learner would hit them:

1. ``drill_loader.load_course`` reads a compiled YAML fixture and upserts
   the ``drill_courses`` + ``drill_modules`` + ``drills`` rows.
2. ``drill_selector.select_next_drill`` returns the first unpassed drill.
3. ``drill_submission.submit_drill`` runs the user code in the subprocess
   sandbox, writes a ``DrillAttempt`` row, and (on pass) hands back the
   next drill id.
4. Re-submitting the same (user, drill) writes a second attempt row and
   the selector advances to the next drill.
5. Wrong code yields ``passed=False`` and the ADHD-safe coaching copy
   defined in :mod:`services.drill_submission` — never the words
   "wrong"/"fail"/"incorrect" and never the red-X emoji.

Why this test exists
--------------------

The unit tests catch shape bugs; this one catches *glue* bugs — e.g. a
router refactor that forgets to flush before ``select_next_drill``, or a
loader change that silently renames a field the submission service
expects. Runtime stays under the 10s budget by:

* Building a tiny fixture inline (1 module × 2 drills) instead of
  touching the 178 KB py4e YAML.
* Monkeypatching ``_locate_course_yaml`` so the loader doesn't do the
  filesystem walk.
* Total subprocess invocations: 2 during load_course's reference-solution
  gate + 3 during submissions = 5, ~400 ms each on Windows.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database import Base

# Importing the models package registers every ORM table with
# ``Base.metadata`` before ``create_all``. Without this the FK target
# tables (``users``) wouldn't exist and ``DrillAttempt`` inserts would
# fail at integrity-check time.
import models  # noqa: F401
from models.drill import Drill, DrillAttempt
from models.user import User
from services import drill_loader
from services.drill_loader import load_course
from services.drill_selector import select_next_drill
from services.drill_submission import submit_drill


# Drill 1: "print(...) contains 'hi'". We capture ``solution``'s
# module-import output via pytest's ``capsys``. Using module import +
# capsys is ~2× cheaper than a nested ``subprocess.run`` because pytest
# only spawns one interpreter per submit, not two — a win under the
# < 10s runtime budget (spec line 70).
_DRILL1_HIDDEN_TESTS = (
    "def test_prints_hi(capsys):\n"
    "    import solution  # noqa: F401  — running solution.py at import\n"
    "    captured = capsys.readouterr()\n"
    "    assert 'hi' in captured.out\n"
)
_DRILL1_REFSOL = 'print("hi")\n'
_DRILL1_CORRECT_SUBMISSION = 'print("hi there")\n'  # still contains "hi"
_DRILL1_WRONG_SUBMISSION = 'print("bye")\n'

# Arithmetic drill — imports ``add`` from the learner's ``solution``
# module, which is how the runner names the submitted-code file.
_DRILL2_HIDDEN_TESTS = (
    "from solution import add\n\n"
    "def test_sum():\n"
    "    assert add(2, 3) == 5\n"
    "    assert add(-1, 1) == 0\n"
)
_DRILL2_REFSOL = "def add(a, b):\n    return a + b\n"
_DRILL2_CORRECT_SUBMISSION = _DRILL2_REFSOL


# ── Fixture harness ─────────────────────────────────────────────────
#
# Runtime budget: the Phase 16c spec caps this file at < 10s. The
# expensive pieces are (a) ``load_course``'s reference-solution gate,
# which spawns a pytest subprocess per drill (~2.5s each cold on
# Windows/Docker), and (b) each ``submit_drill`` call, also a
# subprocess. We amortise the loader cost by running it ONCE per
# module (session-level file DB + module-scoped loader fixture), and
# give each test its own ``User`` row so ``DrillAttempt`` history stays
# naturally isolated without table-truncation gymnastics.


@pytest_asyncio.fixture(scope="module")
async def shared_engine_and_factory() -> AsyncGenerator[
    tuple[object, async_sessionmaker[AsyncSession]], None
]:
    """One file-backed SQLite DB for the whole module.

    File-backed rather than ``:memory:`` because SQLite in-memory is
    per-connection — ``create_all`` and the session end up on different
    empty DBs otherwise. The DB lives for the module lifetime and is
    torn down at the end; per-test isolation is achieved via distinct
    user_ids (see ``user_id`` fixture).
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-drill-flow-e2e-", suffix=".db")
    os.close(fd)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine, factory
    await engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


def _build_fixture_yaml(path: Path) -> None:
    """Write a minimal compiled-course YAML to ``path``.

    Two drills inside one module: the print("hi") one and the add(a,b)
    one. Each ships a ``reference_solution`` that passes its own hidden
    tests so ``load_course``'s subprocess-backed validation gate
    accepts them.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "slug": "e2e-test",
        "title": "E2E Test Course",
        "source": "test",
        "version": "v1.0.0",
        "description": "Inline fixture for the drill-flow integration test.",
        "estimated_hours": 1,
        "modules": [
            {
                "slug": "m1",
                "title": "Module 1",
                "order_index": 1,
                "outcome": "Confirm the glue is wired end-to-end.",
                "drills": [
                    {
                        "slug": "d1-print-hi",
                        "title": 'print("hi")',
                        "why_it_matters": "Prove the runner executes stdout.",
                        "starter_code": "# Write code that prints hi\n",
                        "hidden_tests": _DRILL1_HIDDEN_TESTS,
                        "reference_solution": _DRILL1_REFSOL,
                        "hints": ["Use the print() function."],
                        "skill_tags": ["io"],
                        "source_citation": "e2e fixture",
                        "time_budget_min": 2,
                        "difficulty_layer": 1,
                        "order_index": 1,
                    },
                    {
                        "slug": "d2-add",
                        "title": "add(a, b)",
                        "why_it_matters": "Prove the runner imports solution.py.",
                        "starter_code": "def add(a, b):\n    ...\n",
                        "hidden_tests": _DRILL2_HIDDEN_TESTS,
                        "reference_solution": _DRILL2_REFSOL,
                        "hints": ["Return a + b."],
                        "skill_tags": ["functions", "arithmetic"],
                        "source_citation": "e2e fixture",
                        "time_budget_min": 2,
                        "difficulty_layer": 1,
                        "order_index": 2,
                    },
                ],
            }
        ],
    }
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


@pytest_asyncio.fixture(scope="module")
async def loaded_course(
    shared_engine_and_factory,
    tmp_path_factory: pytest.TempPathFactory,
) -> list[uuid.UUID]:
    """Run ``load_course`` exactly once for the whole module.

    Uses the same monkeypatch trick as ``test_drill_loader``: swap
    ``_locate_course_yaml`` for a stub that points at a temp-built
    fixture. This keeps the loader code path intact (schema validation,
    refsol gate, upsert) without touching its signature, and amortises
    the 2 refsol-gate subprocess calls across every test in the module
    instead of paying them per-test.

    Returns the ordered list of drill ids so each test doesn't have to
    requery them.
    """

    _, factory = shared_engine_and_factory
    tmp_dir = tmp_path_factory.mktemp("e2e_course_yaml")
    fixture_path = (
        tmp_dir / "content" / "drills" / "e2e-test" / "v1.0.0" / "course.yaml"
    )
    _build_fixture_yaml(fixture_path)

    def _locate_stub(course_slug: str, version: str) -> Path | None:
        # Narrow stub: only the e2e-test course is resolved via the
        # fixture; any other slug should fail loudly so a bug in the
        # service layer can't silently pick up the wrong YAML.
        assert course_slug == "e2e-test", f"unexpected slug: {course_slug}"
        assert version == "v1.0.0", f"unexpected version: {version}"
        return fixture_path

    # ``monkeypatch`` is function-scoped; for a module-scoped fixture we
    # patch/restore manually via ``setattr`` to sidestep ty's implicit-
    # shadowing warning (which fires on a direct attribute assign even
    # when the callables have identical signatures — an artefact of
    # ty's flow-sensitivity around module-level function defs).
    original = drill_loader._locate_course_yaml
    setattr(drill_loader, "_locate_course_yaml", _locate_stub)
    try:
        async with factory() as s:
            await load_course(s, "e2e-test", "v1.0.0")
            await s.commit()
            drills = list(
                (await s.execute(select(Drill).order_by(Drill.order_index.asc())))
                .scalars()
                .all()
            )
    finally:
        setattr(drill_loader, "_locate_course_yaml", original)

    assert len(drills) == 2, "fixture should produce exactly 2 drills"
    return [d.id for d in drills]


@pytest_asyncio.fixture
async def session(
    shared_engine_and_factory,
) -> AsyncGenerator[AsyncSession, None]:
    """One fresh ``AsyncSession`` per test on the shared module DB."""

    _, factory = shared_engine_and_factory
    async with factory() as s:
        yield s


@pytest_asyncio.fixture
async def seeded_course(
    session: AsyncSession,
    loaded_course: list[uuid.UUID],
) -> tuple[AsyncSession, uuid.UUID, list[Drill]]:
    """Hand each test a fresh user + the already-loaded drill rows.

    Each test gets its own ``User`` so ``DrillAttempt`` history is
    per-test even though the underlying DB is shared. The drills are
    re-fetched (not stashed as ORM instances on the module-scoped
    fixture) because SQLAlchemy instances are bound to their originating
    session — reusing them across sessions triggers ``DetachedInstanceError``.
    """

    # Seed a learner. A real user row is required because
    # ``DrillAttempt.user_id`` carries a FK to ``users.id``.
    user = User(name="E2E Learner")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    drills = list(
        (
            await session.execute(
                select(Drill)
                .where(Drill.id.in_(loaded_course))
                .order_by(Drill.order_index.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(drills) == 2
    return session, user.id, drills


# ── Scenarios ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_then_next_returns_first_drill(
    seeded_course: tuple[AsyncSession, uuid.UUID, list[Drill]],
) -> None:
    """After load, the selector hands back the lowest-order unpassed drill."""

    session, user_id, drills = seeded_course
    first, second = drills

    nxt = await select_next_drill(session, user_id, "e2e-test")
    assert nxt is not None
    assert nxt.id == first.id
    # Sanity: ``second`` exists but is not yet "next" — selector honours order.
    assert nxt.id != second.id


@pytest.mark.asyncio
async def test_submit_correct_code_passes_and_advances(
    seeded_course: tuple[AsyncSession, uuid.UUID, list[Drill]],
) -> None:
    """Correct submission → passed=True + UA pass-copy + next drill pointer."""

    session, user_id, drills = seeded_course
    first, second = drills

    result = await submit_drill(session, user_id, first.id, _DRILL1_CORRECT_SUBMISSION)

    assert result.passed is True
    assert result.feedback == "Чисто! Тест пройдено."
    assert result.next_drill_id == str(second.id)

    # One attempt row written, marked passed.
    attempts = (
        (
            await session.execute(
                select(DrillAttempt).where(DrillAttempt.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(attempts) == 1
    assert attempts[0].passed is True


@pytest.mark.asyncio
async def test_resubmit_same_drill_writes_second_attempt_and_advances_selector(
    seeded_course: tuple[AsyncSession, uuid.UUID, list[Drill]],
) -> None:
    """Per-attempt history: resubmitting writes a second row; selector moves on."""

    session, user_id, drills = seeded_course
    first, second = drills

    # First submission — passes.
    r1 = await submit_drill(session, user_id, first.id, _DRILL1_CORRECT_SUBMISSION)
    assert r1.passed is True

    # Second submission against the SAME drill — also passes (idempotent).
    # The spec requires two rows in ``drill_attempts`` regardless of the
    # second outcome; running it with correct code is the simplest way
    # to prove the write is per-attempt, not per-unique-pair.
    r2 = await submit_drill(session, user_id, first.id, _DRILL1_CORRECT_SUBMISSION)
    assert r2.passed is True

    attempts = (
        (
            await session.execute(
                select(DrillAttempt).where(
                    DrillAttempt.user_id == user_id,
                    DrillAttempt.drill_id == first.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(attempts) == 2, "each submit should persist a fresh attempt row"

    # Selector now skips the passed drill and returns the second one.
    nxt = await select_next_drill(session, user_id, "e2e-test")
    assert nxt is not None
    assert nxt.id == second.id


@pytest.mark.asyncio
async def test_submit_wrong_code_fails_with_adhd_safe_feedback(
    seeded_course: tuple[AsyncSession, uuid.UUID, list[Drill]],
) -> None:
    """Wrong code → passed=False + coaching copy, never punitive language.

    Per Phase 16c §11 rule 1: the feedback string must never contain
    "wrong"/"failed"/"incorrect" nor the red-X glyph. Pytest output in
    ``runner_output`` may still include them (that's the tool's own
    reporter), but the UI-visible ``feedback`` line is the affect channel
    and stays coaching.
    """

    session, user_id, drills = seeded_course
    first, _ = drills

    result = await submit_drill(session, user_id, first.id, _DRILL1_WRONG_SUBMISSION)

    assert result.passed is False
    assert result.next_drill_id is None

    feedback = result.feedback or ""
    # No red-X glyph (U+274C) — ADHD-safe rule 1.
    assert "❌" not in feedback
    # No punitive vocabulary (case-insensitive, localised + English).
    lowered = feedback.lower()
    for banned in ("wrong", "fail", "incorrect", "помилк", "неправил"):
        assert banned not in lowered, (
            f"feedback must not contain {banned!r}; got {feedback!r}"
        )

    # Attempt was still persisted — history is the source of truth, pass
    # or fail.
    attempts = (
        (
            await session.execute(
                select(DrillAttempt).where(DrillAttempt.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(attempts) == 1
    assert attempts[0].passed is False
