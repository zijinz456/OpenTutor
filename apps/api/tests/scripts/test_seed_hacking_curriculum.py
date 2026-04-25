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
                "match_titles": ["bash", "shell"],
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
                "match_titles": [
                    "owasp",
                    "authentication",
                    "xss",
                    "sql injection",
                    "csrf",
                    "access control",
                ],
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
                "match_titles": [
                    "nmap",
                    "reconnaissance",
                    "scanning",
                    "host discovery",
                ],
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
            {
                "slug": "advanced-web-auth",
                "title": "Advanced web auth and session bypass",
                "difficulty": 3,
                "eta_minutes": 45,
                "module_label": "Web attacks",
                "outcome": (
                    "Bypass weak auth and session logic on systems you have "
                    "permission to test."
                ),
                "match_titles": ["authentication", "password-based login", "jwt"],
                "urls": [
                    "https://portswigger.net/web-security/authentication",
                ],
            },
            {
                "slug": "recon-deep-dive",
                "title": "Recon deep dive",
                "difficulty": 3,
                "eta_minutes": 45,
                "module_label": "Tools",
                "outcome": (
                    "Tune scanning depth and output on systems you have "
                    "permission to test."
                ),
                "match_titles": ["host discovery", "port scanning"],
                "urls": [
                    "https://nmap.org/book/host-discovery-techniques.html",
                ],
            },
            {
                "slug": "idor-and-access-control",
                "title": "IDOR and broken access control",
                "difficulty": 3,
                "eta_minutes": 35,
                "module_label": "Intermediate",
                "outcome": (
                    "Identify IDOR patterns on systems you have permission to test."
                ),
                "match_titles": [
                    "idor",
                    "insecure direct object reference",
                    "broken access control",
                ],
                "urls": [
                    "https://portswigger.net/web-security/access-control/idor",
                ],
            },
            {
                "slug": "file-upload-and-path-traversal",
                "title": "File upload and path traversal",
                "difficulty": 3,
                "eta_minutes": 35,
                "module_label": "Intermediate",
                "outcome": ("Probe upload handlers against Juice Shop on :3100 only."),
                "match_titles": [
                    "file upload",
                    "path traversal",
                    "directory traversal",
                ],
                "urls": [
                    "https://portswigger.net/web-security/file-upload",
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

    source_file = _fake_source_file_for_url(url)

    for index in range(3):
        node = CourseContentTree(
            id=uuid.uuid4(),
            course_id=course_id,
            title=f"Node {index}",
            content=f"Fake content for {url}",
            level=0,
            order_index=index,
            source_file=source_file,
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


def _fake_source_file_for_url(url: str) -> str:
    if "web/http/overview" in url.lower():
        return "Overview of HTTP - HTTP | MDN"
    if "web/http/messages" in url.lower():
        return "HTTP messages - HTTP | MDN"
    if "learning_the_shell" in url.lower():
        return "Learning the Shell - LinuxCommand.org"
    if "top-ten" in url.lower():
        return "OWASP Top Ten"
    if "book/man.html" in url.lower():
        return "Chapter 15. Nmap Reference Guide | Nmap Network Scanning"
    if "burp/documentation/desktop/getting-started" in url.lower():
        return "Getting started with Burp Suite Professional"
    if "juice.shop" in url.lower():
        return "Pwning OWASP Juice Shop"
    if "portswigger.net/web-security/authentication" in url.lower():
        return "Vulnerabilities in password-based login | Web Security Academy"
    if "host-discovery-techniques" in url.lower():
        return "Host Discovery Techniques | Nmap Network Scanning"
    if "access-control/idor" in url.lower():
        return "IDOR vulnerabilities | Web Security Academy"
    if "web-security/file-upload" in url.lower():
        return "File upload vulnerabilities | Web Security Academy"
    return url


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
        rooms_by_slug = {room.slug: room for room in rooms}
        room = rooms_by_slug["network-basics"]
        mapped_count = (
            await db.execute(
                select(func.count(PracticeProblem.id)).where(
                    PracticeProblem.path_room_id == room.id
                )
            )
        ).scalar_one()
        idor_room = rooms_by_slug["idor-and-access-control"]
        upload_room = rooms_by_slug["file-upload-and-path-traversal"]
        idor_mapped = (
            await db.execute(
                select(func.count(PracticeProblem.id)).where(
                    PracticeProblem.path_room_id == idor_room.id
                )
            )
        ).scalar_one()
        upload_mapped = (
            await db.execute(
                select(func.count(PracticeProblem.id)).where(
                    PracticeProblem.path_room_id == upload_room.id
                )
            )
        ).scalar_one()

    assert len(paths) == 1
    assert paths[0].slug == "hacking-foundations"
    assert paths[0].track_id == "hacking_foundations"
    assert len(rooms) == 10
    assert "idor-and-access-control" in rooms_by_slug
    assert "file-upload-and-path-traversal" in rooms_by_slug
    assert (
        room.outcome == "Explain HTTP requests on systems you have permission to test."
    )
    assert room.difficulty == 1
    assert room.eta_minutes == 25
    assert room.module_label == "Basics"
    assert mapped_count == 6

    assert idor_room.difficulty == 3
    assert idor_room.eta_minutes == 35
    assert idor_room.module_label == "Intermediate"
    assert (
        idor_room.outcome
        == "Identify IDOR patterns on systems you have permission to test."
    )
    assert idor_mapped >= 1

    assert upload_room.difficulty == 3
    assert upload_room.eta_minutes == 35
    assert upload_room.module_label == "Intermediate"
    assert (
        upload_room.outcome == "Probe upload handlers against Juice Shop on :3100 only."
    )
    assert upload_mapped >= 1


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
    assert room_count == 10
    assert job_count == 11
    assert problem_count == 33
    assert mapped_count == 33


@pytest.mark.asyncio
async def test_seed_maps_specific_titles_before_broad_room_hints(
    session_factory, fake_yaml
):
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
        rooms = {
            room.slug: room
            for room in (await db.execute(select(PathRoom))).scalars().all()
        }
        advanced_count = (
            await db.execute(
                select(func.count(PracticeProblem.id)).where(
                    PracticeProblem.path_room_id == rooms["advanced-web-auth"].id
                )
            )
        ).scalar_one()
        recon_deep_count = (
            await db.execute(
                select(func.count(PracticeProblem.id)).where(
                    PracticeProblem.path_room_id == rooms["recon-deep-dive"].id
                )
            )
        ).scalar_one()

    assert advanced_count == 3
    assert recon_deep_count == 3
