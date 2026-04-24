"""Tests for the hacking curriculum seed script.

The script must:
1. Upsert one hacking path plus one room from a minimal fixture yaml.
2. Reuse the ingest pipeline seam to create cards from URLs.
3. Map generated cards into the room via ``_map_cards_to_room``.
4. Stay idempotent on rerun by skipping already-successful ingests.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base
from models.content import CourseContentTree
from models.ingestion import IngestionJob
from models.learning_path import LearningPath, PathRoom
from models.practice import PracticeProblem
from scripts.seed_hacking_curriculum import main


@pytest_asyncio.fixture
async def session_factory():
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
    doc = {
        "path": {
            "slug": "hacking-foundations",
            "title": "Hacking - Foundations",
            "track_id": "hacking_foundations",
            "difficulty": "beginner",
            "description": "Safe, legal, practical.",
        },
        "modules": [
            {
                "slug": "network-basics",
                "title": "Networking and HTTP basics",
                "difficulty": 1,
                "eta_minutes": 25,
                "module_label": "Basics",
                "outcome": (
                    "Explain HTTP requests on systems you have permission to test."
                ),
                "match_titles": ["http"],
                "urls": [
                    "https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview",
                    "https://developer.mozilla.org/en-US/docs/Web/HTTP/Messages",
                ],
            },
            {
                "slug": "linux-and-bash",
                "title": "Linux command line and Bash for recon",
                "difficulty": 1,
                "eta_minutes": 30,
                "module_label": "Basics",
                "outcome": (
                    "Collect host info on systems you have permission to test."
                ),
                "match_titles": ["bash"],
                "urls": [
                    "https://linuxcommand.org/lc3_learning_the_shell.php",
                ],
            },
            {
                "slug": "web-security-owasp",
                "title": "OWASP Top 10 - web attacks",
                "difficulty": 2,
                "eta_minutes": 45,
                "module_label": "Web attacks",
                "outcome": (
                    "Recognise common web bugs on systems you have permission to test."
                ),
                "match_titles": ["owasp"],
                "urls": [
                    "https://owasp.org/www-project-top-ten/",
                ],
            },
            {
                "slug": "recon-and-scanning",
                "title": "Recon and scanning",
                "difficulty": 2,
                "eta_minutes": 30,
                "module_label": "Tools",
                "outcome": (
                    "Map exposed services on systems you have permission to test."
                ),
                "match_titles": ["nmap"],
                "urls": [
                    "https://nmap.org/book/man.html",
                ],
            },
            {
                "slug": "exploitation-toolkit",
                "title": "Exploitation toolkit - Burp and Metasploit",
                "difficulty": 3,
                "eta_minutes": 40,
                "module_label": "Tools",
                "outcome": (
                    "Modify vulnerable requests on systems you have permission to test."
                ),
                "match_titles": ["burp"],
                "urls": [
                    "https://portswigger.net/burp/documentation/desktop/getting-started",
                ],
            },
            {
                "slug": "juice-shop-practice",
                "title": "Practice - Juice Shop local lab",
                "difficulty": 3,
                "eta_minutes": 60,
                "module_label": "Practice",
                "outcome": ("Exploit a local lab against Juice Shop on :3100 only."),
                "match_titles": ["juice shop"],
                "urls": [
                    "https://pwning.owasp-juice.shop/",
                ],
            },
        ],
    }
    yaml_path = tmp_path / "content" / "hacking" / "curriculum.yaml"
    yaml_path.parent.mkdir(parents=True)
    yaml_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return yaml_path


async def _fake_ingest_url(
    db,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    url: str,
    timeout_seconds: float,
):
    del timeout_seconds

    job = IngestionJob(
        id=uuid.uuid4(),
        user_id=user_id,
        source_type="url",
        original_filename=url.rsplit("/", 1)[-1] or "index.html",
        url=url,
        course_id=course_id,
        course_preset=True,
        status="completed",
        progress_percent=100,
        phase_label="Ready",
        embedding_status="completed",
        dispatched=True,
    )
    db.add(job)
    await db.flush()

    for index in range(3):
        node = CourseContentTree(
            id=uuid.uuid4(),
            course_id=course_id,
            title=f"Node {index}",
            content=f"Fake content for {url}",
            level=0,
            order_index=index,
            source_file=url,
            source_type="url",
            content_category="knowledge",
        )
        db.add(node)
        await db.flush()

        db.add(
            PracticeProblem(
                id=uuid.uuid4(),
                course_id=course_id,
                content_node_id=node.id,
                question_type="multiple_choice",
                question=f"{url} :: card {index}",
                options={"a": "one", "b": "two"},
                correct_answer="one",
                explanation="Because fixture.",
            )
        )

    await db.flush()
    return job


@pytest.mark.asyncio
async def test_seed_creates_path_room_and_maps_cards(session_factory, fake_yaml):
    rc = await main(
        dry_run=False,
        yaml_path_override=fake_yaml,
        session_factory=session_factory,
        ingest_url_func=_fake_ingest_url,
        sleep_seconds=0,
        timeout_seconds=1,
    )
    assert rc == 0

    async with session_factory() as db:
        paths = (await db.execute(select(LearningPath))).scalars().all()
        rooms = (await db.execute(select(PathRoom))).scalars().all()
        room = next(room for room in rooms if room.slug == "network-basics")
        mapped_count = (
            await db.execute(
                select(func.count(PracticeProblem.id)).where(
                    PracticeProblem.path_room_id == room.id
                )
            )
        ).scalar_one()

    assert len(paths) == 1
    assert paths[0].slug == "hacking-foundations"
    assert paths[0].track_id == "hacking_foundations"
    assert len(rooms) == 6
    assert (
        room.outcome == "Explain HTTP requests on systems you have permission to test."
    )
    assert room.difficulty == 1
    assert room.eta_minutes == 25
    assert room.module_label == "Basics"
    assert mapped_count == 6


@pytest.mark.asyncio
async def test_seed_is_idempotent_on_rerun(session_factory, fake_yaml):
    for _ in range(2):
        rc = await main(
            dry_run=False,
            yaml_path_override=fake_yaml,
            session_factory=session_factory,
            ingest_url_func=_fake_ingest_url,
            sleep_seconds=0,
            timeout_seconds=1,
        )
        assert rc == 0

    async with session_factory() as db:
        path_count = (
            await db.execute(select(func.count(LearningPath.id)))
        ).scalar_one()
        room_count = (await db.execute(select(func.count(PathRoom.id)))).scalar_one()
        job_count = (await db.execute(select(func.count(IngestionJob.id)))).scalar_one()
        problem_count = (
            await db.execute(select(func.count(PracticeProblem.id)))
        ).scalar_one()
        mapped_count = (
            await db.execute(
                select(func.count(PracticeProblem.id)).where(
                    PracticeProblem.path_room_id.is_not(None)
                )
            )
        ).scalar_one()

    assert path_count == 1
    assert room_count == 6
    assert job_count == 7
    assert problem_count == 21
    assert mapped_count == 21
