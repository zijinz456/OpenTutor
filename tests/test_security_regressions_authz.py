"""Security regressions: object-level authorization and scope checks."""

import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import database as database_module
from config import settings
from database import Base, get_db
from main import app
from models.content import CourseContentTree
from models.course import Course
from models.ingestion import IngestionJob
from models.practice import PracticeProblem
from models.user import User
from services.auth.dependency import get_current_user


@pytest_asyncio.fixture
async def authz_client():
    """Create isolated app client with explicit A/B users."""
    fd, db_path = tempfile.mkstemp(prefix="opentutor-authz-", suffix=".db")
    os.close(fd)
    upload_dir = Path(tempfile.mkdtemp(prefix="opentutor-authz-uploads-")).resolve()

    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        pool_pre_ping=False,
        poolclass=NullPool,
    )
    test_session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    user_ids = {"user_a": uuid.uuid4(), "user_b": uuid.uuid4()}
    async with test_session_factory() as db:
        db.add_all(
            [
                User(id=user_ids["user_a"], name="User A", email="user-a@opentutor.dev"),
                User(id=user_ids["user_b"], name="User B", email="user-b@opentutor.dev"),
            ]
        )
        await db.commit()

    async def _override_get_db():
        async with test_session_factory() as session:
            yield session

    async def _override_get_current_user(request: Request):
        alias = request.headers.get("x-test-user", "user_a")
        if alias not in user_ids:
            alias = "user_a"
        request.state.user_id = str(user_ids[alias])
        request.state.deployment_mode = "multi_user"
        return SimpleNamespace(id=user_ids[alias], is_active=True)

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.state.test_session_factory = test_session_factory

    original_async_session = database_module.async_session
    database_module.async_session = test_session_factory
    original_upload_dir = settings.upload_dir
    settings.upload_dir = str(upload_dir)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "session_factory": test_session_factory,
            "users": user_ids,
            "upload_dir": upload_dir,
        }

    settings.upload_dir = original_upload_dir
    database_module.async_session = original_async_session
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    if hasattr(app.state, "test_session_factory"):
        delattr(app.state, "test_session_factory")

    await test_engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.mark.asyncio
async def test_content_file_endpoints_block_cross_user_access(authz_client):
    client = authz_client["client"]
    session_factory = authz_client["session_factory"]
    users = authz_client["users"]
    upload_dir = authz_client["upload_dir"]

    async with session_factory() as db:
        owner_course = Course(user_id=users["user_b"], name="Owner Course", description="owner")
        db.add(owner_course)
        await db.flush()

        owned_file = upload_dir / "owner-note.md"
        owned_file.write_text("# owner", encoding="utf-8")
        job = IngestionJob(
            user_id=users["user_b"],
            course_id=owner_course.id,
            source_type="file",
            original_filename="owner-note.md",
            file_path=str(owned_file),
            status="completed",
            embedding_status="completed",
            nodes_created=1,
        )
        db.add(job)
        await db.commit()
        await db.refresh(owner_course)
        await db.refresh(job)

    # Cross-user access must look like missing resources (404)
    denied_list = await client.get(
        f"/api/content/files/by-course/{owner_course.id}",
        headers={"x-test-user": "user_a"},
    )
    assert denied_list.status_code == 404

    denied_download = await client.get(
        f"/api/content/files/{job.id}",
        headers={"x-test-user": "user_a"},
    )
    assert denied_download.status_code == 404

    # Owner can list and download
    owner_list = await client.get(
        f"/api/content/files/by-course/{owner_course.id}",
        headers={"x-test-user": "user_b"},
    )
    assert owner_list.status_code == 200
    assert len(owner_list.json()) == 1

    owner_download = await client.get(
        f"/api/content/files/{job.id}",
        headers={"x-test-user": "user_b"},
    )
    assert owner_download.status_code == 200
    assert owner_download.text == "# owner"


@pytest.mark.asyncio
async def test_quiz_endpoints_block_cross_user_access(authz_client):
    client = authz_client["client"]
    session_factory = authz_client["session_factory"]
    users = authz_client["users"]

    async with session_factory() as db:
        owner_course = Course(user_id=users["user_b"], name="Owner Quiz Course", description="quiz")
        db.add(owner_course)
        await db.flush()
        problem = PracticeProblem(
            course_id=owner_course.id,
            question_type="mc",
            question="2 + 2 = ?",
            options={"a": "3", "b": "4"},
            correct_answer="4",
            explanation="4 is correct",
            order_index=1,
            source="generated",
        )
        db.add(problem)
        await db.commit()
        await db.refresh(owner_course)
        await db.refresh(problem)

    denied_list = await client.get(
        f"/api/quiz/{owner_course.id}",
        headers={"x-test-user": "user_a"},
    )
    assert denied_list.status_code == 404

    denied_submit = await client.post(
        "/api/quiz/submit",
        headers={"x-test-user": "user_a"},
        json={"problem_id": str(problem.id), "user_answer": "4"},
    )
    assert denied_submit.status_code == 404

    owner_list = await client.get(
        f"/api/quiz/{owner_course.id}",
        headers={"x-test-user": "user_b"},
    )
    assert owner_list.status_code == 200
    assert len(owner_list.json()) == 1

    owner_submit = await client.post(
        "/api/quiz/submit",
        headers={"x-test-user": "user_b"},
        json={"problem_id": str(problem.id), "user_answer": "4"},
    )
    assert owner_submit.status_code == 200
    assert owner_submit.json()["is_correct"] is True


@pytest.mark.asyncio
async def test_extract_quiz_rejects_content_node_not_in_course(authz_client, monkeypatch):
    client = authz_client["client"]
    session_factory = authz_client["session_factory"]
    users = authz_client["users"]

    async def _noop_llm_ready(*_args, **_kwargs):
        return None

    monkeypatch.setattr("routers.quiz_generation.ensure_llm_ready", _noop_llm_ready)

    async with session_factory() as db:
        course_a = Course(user_id=users["user_a"], name="Course A")
        course_b = Course(user_id=users["user_a"], name="Course B")
        db.add_all([course_a, course_b])
        await db.flush()

        node = CourseContentTree(
            course_id=course_b.id,
            title="Foreign Node",
            content="Node content",
            level=1,
            order_index=1,
            source_type="manual",
        )
        db.add(node)
        await db.commit()
        await db.refresh(course_a)
        await db.refresh(node)

    resp = await client.post(
        "/api/quiz/extract",
        headers={"x-test-user": "user_a"},
        json={
            "course_id": str(course_a.id),
            "content_node_id": str(node.id),
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_system_analytics_enforces_user_scope(authz_client):
    # system_analytics router unregistered in feature-pruning sprint (2026-03-12)
    client = authz_client["client"]

    resp = await client.get(
        "/api/analytics/system",
        headers={"x-test-user": "user_a"},
    )
    assert resp.status_code == 404
