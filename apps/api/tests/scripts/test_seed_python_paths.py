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
slash, http vs https, query string, fragment, ``www.`` prefix), and
Phase 12 Slice 1 Part A coverage of the structured ``SeedSummary``
dataclass + the ``--report-json`` JSON serializer helper.

Uses an async SQLite engine via the app's own ``Base.metadata`` so the
tests exercise the exact schema. The script's ``session_factory``
argument is the injection seam — no monkeypatch of the global
``database.async_session`` needed.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
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
from scripts.seed_python_paths import (
    SeedSummary,
    _url_match_key,
    _write_report_json,
    main,
)


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
    summary = await main(
        dry_run=False, yaml_path_override=fake_yaml, session_factory=session_factory
    )
    assert isinstance(summary, SeedSummary)
    assert summary.exit_code == 0

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
    assert all(r.outcome == "Complete this mission" for r in rooms)
    assert all(r.difficulty == 2 for r in rooms)
    assert all(r.eta_minutes == 15 for r in rooms)
    assert all(r.module_label == "" for r in rooms)


# ── 2. Idempotent re-run — no duplicates on second call ────────────────


@pytest.mark.asyncio
async def test_seed_is_idempotent(session_factory, fake_yaml):
    """Running the seed twice yields the same paths + rooms counts."""
    for _ in range(2):
        summary = await main(
            dry_run=False,
            yaml_path_override=fake_yaml,
            session_factory=session_factory,
        )
        assert summary.exit_code == 0

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

    summary = await main(
        dry_run=False, yaml_path_override=fake_yaml, session_factory=session_factory
    )
    assert summary.exit_code == 0

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


# ── 3.5. match_titles override ─────────────────────────────────────────


@pytest.fixture
def fake_yaml_with_match_titles(tmp_path: Path) -> Path:
    """Yaml with a module that declares ``match_titles`` — covers the
    2026-04-24 orphan fix for cards whose scraped page title doesn't
    substring-match the module URL slug (e.g. Real Python articles
    titled "Reading and Writing Files in Python (Guide)" should map
    to ``py_files`` despite the URL slug being ``read-write-files``).
    """
    doc = {
        "tracks": [
            {
                "id": "python_fundamentals",
                "title": "Python Fundamentals",
                "difficulty": "beginner",
                "modules": [
                    {
                        "id": "py_files",
                        "title": "File I/O: read, write, with-statement",
                        "match_titles": [
                            "reading and writing files",
                            "file i/o",
                        ],
                        "sources": [
                            {"url": "https://realpython.com/read-write-files-python/"}
                        ],
                    },
                ],
            }
        ]
    }
    yaml_path = tmp_path / "content" / "python_full_curriculum.yaml"
    yaml_path.parent.mkdir(parents=True)
    yaml_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return yaml_path


@pytest.mark.asyncio
async def test_match_titles_override_maps_orphan_by_page_title(
    session_factory, fake_yaml_with_match_titles
):
    """A card whose parent node's source_file is the scraped page title
    (not the URL) gets mapped via the module's ``match_titles`` list
    even when the URL slug doesn't substring-match the title."""
    problem_id = uuid.uuid4()
    await _seed_course_with_problems(
        session_factory,
        # source_file here is the scraped page title, not the URL —
        # this is what the current ingest pipeline stores for realpython
        # articles (see SESSION_STATE quirks on ``source_file``).
        url_by_problem={
            problem_id: "Reading and Writing Files in Python (Guide) – Real Python"
        },
    )

    summary = await main(
        dry_run=False,
        yaml_path_override=fake_yaml_with_match_titles,
        session_factory=session_factory,
    )
    assert summary.exit_code == 0

    from sqlalchemy import select

    async with session_factory() as db:
        room = (
            await db.execute(select(PathRoom).where(PathRoom.slug == "py_files"))
        ).scalar_one()
        mapped = (
            await db.execute(
                select(PracticeProblem).where(PracticeProblem.id == problem_id)
            )
        ).scalar_one()

    assert mapped.path_room_id == room.id
    assert mapped.task_order == 0


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

    summary = await main(
        dry_run=False, yaml_path_override=fake_yaml, session_factory=session_factory
    )
    assert summary.exit_code == 0

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
    summary = await main(
        dry_run=True, yaml_path_override=fake_yaml, session_factory=session_factory
    )
    assert summary.exit_code == 0
    assert summary.dry_run is True

    async with session_factory() as db:
        paths = (await db.execute(__import___select_paths())).scalars().all()
        rooms = (await db.execute(__import___select_rooms())).scalars().all()

    assert paths == []
    assert rooms == []


# ── 6. SeedSummary structured report (Phase 12 Slice 1 Part A) ─────────


@pytest.mark.asyncio
async def test_seed_summary_counts_match_db_state(session_factory, fake_yaml):
    """SeedSummary fields equal the DB rowcounts after a non-dry run.

    The fixture yaml has 2 tracks × 3 modules = 6 rooms. We pre-seed
    5 problems pointing at ``py_intro`` and 2 at ``py_classes`` so the
    cards-mapped counter and the per-room map can be asserted exactly.
    """
    intro_ids = [uuid.uuid4() for _ in range(5)]
    classes_ids = [uuid.uuid4() for _ in range(2)]
    orphan_ids = [uuid.uuid4() for _ in range(3)]
    url_by_problem: dict[uuid.UUID, str | None] = {}
    for pid in intro_ids:
        url_by_problem[pid] = "https://docs.python.org/3/tutorial/introduction.html"
    for pid in classes_ids:
        url_by_problem[pid] = (
            "https://realpython.com/python3-object-oriented-programming/"
        )
    for pid in orphan_ids:
        url_by_problem[pid] = "https://random.example.com/never-matched"

    await _seed_course_with_problems(session_factory, url_by_problem=url_by_problem)

    summary = await main(
        dry_run=False, yaml_path_override=fake_yaml, session_factory=session_factory
    )

    assert summary.exit_code == 0
    assert summary.dry_run is False
    assert summary.paths_upserted == 2
    assert summary.rooms_upserted == 6
    assert summary.cards_mapped == 7  # 5 intro + 2 classes
    # Per-room map covers every module and matches the per-room counts.
    assert summary.per_room_mapped["py_intro"] == 5
    assert summary.per_room_mapped["py_classes"] == 2
    # Modules with no matching problems still appear with a 0 entry —
    # the loop writes the key for every module it processes.
    assert summary.per_room_mapped["py_controlflow"] == 0
    assert summary.per_room_mapped["py_functions"] == 0
    assert summary.per_room_mapped["py_decorators"] == 0
    assert summary.per_room_mapped["py_context_managers"] == 0
    assert sum(summary.per_room_mapped.values()) == summary.cards_mapped
    # Orphan count reflects the 3 unrelated-URL problems — we do NOT
    # assert "reduced from N to M"; brief explicitly forbids invented
    # orphan-reduction claims, just count what actually happened.
    assert summary.orphan_count == 3
    # capstone_updates should fire for the 2 rooms that received cards.
    assert summary.capstone_updates == 2
    assert summary.yaml_path == str(fake_yaml)


@pytest.mark.asyncio
async def test_seed_summary_dry_run_does_not_count_capstones(
    session_factory, fake_yaml
):
    """On dry-run we skip capstone backfill, so its counter stays 0."""
    summary = await main(
        dry_run=True, yaml_path_override=fake_yaml, session_factory=session_factory
    )

    assert summary.exit_code == 0
    assert summary.dry_run is True
    assert summary.paths_upserted == 2
    assert summary.rooms_upserted == 6
    # No problems pre-seeded → cards_mapped == 0 and per-room all zeros.
    assert summary.cards_mapped == 0
    assert all(v == 0 for v in summary.per_room_mapped.values())
    # Capstone backfill is gated behind the non-dry branch.
    assert summary.capstone_updates == 0


@pytest.mark.asyncio
async def test_seed_summary_missing_yaml_returns_exit_2(session_factory, tmp_path):
    """When the curriculum yaml is absent, summary.exit_code == 2 and
    no DB writes happen — counts stay at their zero defaults."""
    missing = tmp_path / "does-not-exist.yaml"
    summary = await main(
        dry_run=False, yaml_path_override=missing, session_factory=session_factory
    )

    assert summary.exit_code == 2
    assert summary.paths_upserted == 0
    assert summary.rooms_upserted == 0
    assert summary.cards_mapped == 0
    assert summary.per_room_mapped == {}
    assert summary.yaml_path is None


def test_write_report_json_serializes_summary(tmp_path):
    """``_write_report_json`` produces valid JSON containing every
    SeedSummary field via ``dataclasses.asdict``."""
    summary = SeedSummary(
        paths_upserted=2,
        rooms_upserted=6,
        cards_mapped=7,
        capstone_updates=2,
        orphan_count=3,
        per_room_mapped={"py_intro": 5, "py_classes": 2},
        dry_run=False,
        yaml_path="/tmp/curriculum.yaml",
        exit_code=0,
    )
    report_path = tmp_path / "nested" / "report.json"
    _write_report_json(summary, report_path)

    assert report_path.is_file()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    # Every dataclass field is round-tripped — keys identical to asdict.
    assert payload == asdict(summary)


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
