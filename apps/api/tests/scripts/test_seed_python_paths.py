"""Tests for Phase 16a T2 — ``seed_python_paths`` idempotent seed.

Covers the five T2 merge-criteria:

1. Fresh DB + yaml with N tracks × M modules → N paths + (N*M) rooms.
2. Re-running ``main(dry_run=False)`` twice produces no duplicates.
3. Pre-seeded practice problems whose parent ``CourseContentTree.
   source_file`` matches a module's curated URL are mapped to that
   module's room with ``task_order`` 0..k-1.
4. Problems without a ``source_file`` (or with an unrelated URL) stay
   orphan — ``path_room_id IS NULL`` after the run.
5. ``dry_run=True`` rolls back — no paths / rooms / mappings persist.

Plus URL-normalization unit tests for ``_url_match_key`` (trailing
slash, http vs https, query string, fragment, ``www.`` prefix).

Uses an async SQLite engine via the app's own ``Base.metadata`` so the
tests exercise the exact schema. The script's ``session_factory``
argument is the injection seam — no monkeypatch of the global
``database.async_session`` needed.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import Base
from models.content import CourseContentTree
from models.course import Course
from models.learning_path import LearningPath, PathRoom
from models.practice import PracticeProblem
from models.user import User
from scripts.seed_python_paths import _url_match_key, main


# ── fixtures ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_factory():
    """Return an ``async_sessionmaker`` bound to a fresh in-memory SQLite
    engine with the full app schema created.

    StaticPool keeps the same in-memory DB across sessions opened from
    the same engine — required because SQLite ``:memory:`` drops
    on-connection-close otherwise.
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


@pytest.fixture
def fake_yaml(tmp_path: Path) -> Path:
    """Write a small 2-track × 3-module curriculum yaml and return its path."""
    doc = {
        "tracks": [
            {
                "id": "python_fundamentals",
                "title": "Python Fundamentals",
                "difficulty": "beginner",
                "why": "Foundations first.",
                "modules": [
                    {
                        "id": "py_intro",
                        "title": "Intro",
                        "cards_target": 15,
                        "sources": [
                            {
                                "url": "https://docs.python.org/3/tutorial/introduction.html"
                            }
                        ],
                    },
                    {
                        "id": "py_controlflow",
                        "title": "Control flow",
                        "cards_target": 18,
                        "sources": [
                            {
                                "url": "https://docs.python.org/3/tutorial/controlflow.html"
                            }
                        ],
                    },
                    {
                        "id": "py_functions",
                        "title": "Functions",
                        "cards_target": 15,
                        "sources": [
                            {
                                "url": "https://realpython.com/defining-your-own-python-function/"
                            }
                        ],
                    },
                ],
            },
            {
                "id": "python_intermediate",
                "title": "Python Intermediate",
                "difficulty": "intermediate",
                "modules": [
                    {
                        "id": "py_classes",
                        "title": "Classes",
                        "cards_target": 18,
                        "sources": [
                            {
                                "url": "https://realpython.com/python3-object-oriented-programming/"
                            }
                        ],
                    },
                    {
                        "id": "py_decorators",
                        "title": "Decorators",
                        "cards_target": 14,
                        "sources": [
                            {
                                "url": "https://realpython.com/primer-on-python-decorators/"
                            }
                        ],
                    },
                    {
                        "id": "py_context_managers",
                        "title": "Context managers",
                        "cards_target": 10,
                        "sources": [
                            {"url": "https://realpython.com/python-with-statement/"}
                        ],
                    },
                ],
            },
        ]
    }
    yaml_path = tmp_path / "content" / "python_full_curriculum.yaml"
    yaml_path.parent.mkdir(parents=True)
    yaml_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return yaml_path


async def _seed_course_with_problems(
    session_factory, *, url_by_problem: dict[uuid.UUID, str | None]
) -> uuid.UUID:
    """Create one user + one course + N content-tree nodes + N problems.

    ``url_by_problem`` maps a pre-generated problem UUID to the
    ``source_file`` its parent content node should carry (or ``None``
    to leave the problem without a content node at all, simulating
    pre-AI baseline cards).

    Returns the course id so tests can query it.
    """
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    async with session_factory() as db:
        db.add(User(id=user_id, name="Seed Tester"))
        await db.flush()
        db.add(Course(id=course_id, user_id=user_id, name="Python Basics"))
        await db.flush()
        for problem_id, url in url_by_problem.items():
            content_node_id: uuid.UUID | None = None
            if url is not None:
                content_node_id = uuid.uuid4()
                db.add(
                    CourseContentTree(
                        id=content_node_id,
                        course_id=course_id,
                        title="node",
                        source_file=url,
                        source_type="url",
                    )
                )
            db.add(
                PracticeProblem(
                    id=problem_id,
                    course_id=course_id,
                    content_node_id=content_node_id,
                    question_type="mc",
                    question="?",
                    correct_answer="x",
                )
            )
        await db.commit()
    return course_id


# ── 1. Fresh DB — 2 paths + 6 rooms materialize ────────────────────────


@pytest.mark.asyncio
async def test_seed_creates_paths_and_rooms(session_factory, fake_yaml):
    """A fresh DB + fixture yaml produces exactly N paths and N*M rooms."""
    rc = await main(
        dry_run=False, yaml_path_override=fake_yaml, session_factory=session_factory
    )
    assert rc == 0

    async with session_factory() as db:
        paths = (await db.execute(__import___select_paths())).scalars().all()
        rooms = (await db.execute(__import___select_rooms())).scalars().all()

    assert len(paths) == 2
    assert {p.slug for p in paths} == {"python-fundamentals", "python-intermediate"}
    assert len(rooms) == 6
    # room_order is 0-based dense per path
    fundamentals = next(p for p in paths if p.slug == "python-fundamentals")
    fund_rooms = sorted(
        (r for r in rooms if r.path_id == fundamentals.id),
        key=lambda r: r.room_order,
    )
    assert [r.room_order for r in fund_rooms] == [0, 1, 2]
    expected_slugs = ["py_intro", "py_controlflow", "py_functions"]
    assert [r.slug for r in fund_rooms] == expected_slugs


# ── 2. Idempotent re-run — no duplicates on second call ────────────────


@pytest.mark.asyncio
async def test_seed_is_idempotent(session_factory, fake_yaml):
    """Running the seed twice yields the same paths + rooms counts."""
    for _ in range(2):
        rc = await main(
            dry_run=False,
            yaml_path_override=fake_yaml,
            session_factory=session_factory,
        )
        assert rc == 0

    async with session_factory() as db:
        paths = (await db.execute(__import___select_paths())).scalars().all()
        rooms = (await db.execute(__import___select_rooms())).scalars().all()

    assert len(paths) == 2
    assert len(rooms) == 6


# ── 3. Card mapping by source_file URL ─────────────────────────────────


@pytest.mark.asyncio
async def test_cards_mapped_by_source_file(session_factory, fake_yaml):
    """Problems whose parent node's source_file matches a module's URL
    get ``path_room_id`` assigned and ``task_order`` 0..k-1."""
    problem_ids = [uuid.uuid4() for _ in range(5)]
    await _seed_course_with_problems(
        session_factory,
        url_by_problem={
            pid: "https://docs.python.org/3/tutorial/introduction.html"
            for pid in problem_ids
        },
    )

    rc = await main(
        dry_run=False, yaml_path_override=fake_yaml, session_factory=session_factory
    )
    assert rc == 0

    from sqlalchemy import select

    async with session_factory() as db:
        py_intro = (
            await db.execute(select(PathRoom).where(PathRoom.slug == "py_intro"))
        ).scalar_one()
        mapped = (
            (
                await db.execute(
                    select(PracticeProblem).where(PracticeProblem.id.in_(problem_ids))
                )
            )
            .scalars()
            .all()
        )

    assert all(p.path_room_id == py_intro.id for p in mapped)
    assert sorted(p.task_order for p in mapped) == [0, 1, 2, 3, 4]


# ── 4. Orphans stay orphan ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_orphan_cards_stay_unmapped(session_factory, fake_yaml):
    """Problems with no source_file or an unrelated URL keep
    ``path_room_id IS NULL``."""
    no_url_id = uuid.uuid4()
    unrelated_id = uuid.uuid4()
    await _seed_course_with_problems(
        session_factory,
        url_by_problem={
            no_url_id: None,  # no content node at all
            unrelated_id: "https://random.example.com/some-article",
        },
    )

    rc = await main(
        dry_run=False, yaml_path_override=fake_yaml, session_factory=session_factory
    )
    assert rc == 0

    from sqlalchemy import select

    async with session_factory() as db:
        rows = (
            (
                await db.execute(
                    select(PracticeProblem).where(
                        PracticeProblem.id.in_([no_url_id, unrelated_id])
                    )
                )
            )
            .scalars()
            .all()
        )

    assert all(p.path_room_id is None for p in rows)
    assert all(p.task_order is None for p in rows)


# ── 5. --dry-run rolls back ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dry_run_rolls_back(session_factory, fake_yaml):
    """``dry_run=True`` must not leave any paths or rooms in the DB."""
    rc = await main(
        dry_run=True, yaml_path_override=fake_yaml, session_factory=session_factory
    )
    assert rc == 0

    async with session_factory() as db:
        paths = (await db.execute(__import___select_paths())).scalars().all()
        rooms = (await db.execute(__import___select_rooms())).scalars().all()

    assert paths == []
    assert rooms == []


# ── URL normalization unit tests ───────────────────────────────────────


@pytest.mark.parametrize(
    "a,b",
    [
        # Trailing slash stripped.
        (
            "https://docs.python.org/3/tutorial/",
            "https://docs.python.org/3/tutorial",
        ),
        # Case insensitive host + path.
        (
            "HTTPS://DOCS.PYTHON.ORG/3/Tutorial",
            "https://docs.python.org/3/tutorial",
        ),
        # Query string stripped.
        (
            "https://docs.python.org/3/tutorial/introduction.html?foo=bar",
            "https://docs.python.org/3/tutorial/introduction.html",
        ),
        # Fragment stripped.
        (
            "https://docs.python.org/3/tutorial/introduction.html#section-1",
            "https://docs.python.org/3/tutorial/introduction.html",
        ),
    ],
)
def test_url_match_key_normalizes(a, b):
    """Cosmetic differences between two URLs collapse to the same key."""
    assert _url_match_key(a) == _url_match_key(b)


def test_url_match_key_keeps_www_distinct():
    """``www.`` prefix is deliberately NOT normalized — kept distinct."""
    assert _url_match_key("https://www.example.com/x") != _url_match_key(
        "https://example.com/x"
    )


def test_url_match_key_keeps_different_paths_distinct():
    """Different paths on the same host don't collide."""
    assert _url_match_key(
        "https://docs.python.org/3/tutorial/introduction.html"
    ) != _url_match_key("https://docs.python.org/3/tutorial/controlflow.html")


# ── helpers ────────────────────────────────────────────────────────────


def __import___select_paths():
    """``select(LearningPath)`` — wrapped so each test import stays local."""
    from sqlalchemy import select

    return select(LearningPath)


def __import___select_rooms():
    from sqlalchemy import select

    return select(PathRoom)
