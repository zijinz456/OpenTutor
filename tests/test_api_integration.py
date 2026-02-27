"""API integration tests using httpx AsyncClient.

These tests require a PostgreSQL database (auto-created in conftest).
Run with: pytest tests/test_api_integration.py -v
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from main import app
from config import settings
from database import get_db, Base

TEST_EMAIL = f"test-{uuid.uuid4().hex[:8]}@opentutor.dev"


@pytest_asyncio.fixture
async def client():
    """Create per-test client with an isolated PostgreSQL schema."""
    schema = f"test_{uuid.uuid4().hex[:10]}"
    test_engine = create_async_engine(
        settings.database_url,
        echo=False,
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )
    test_session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with test_engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as exc:
            pytest.skip(f"pgvector extension unavailable for integration tests: {exc}")
        await conn.run_sync(Base.metadata.create_all)

    async def _override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await test_engine.dispose()


# ── Health ──

@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


# ── Course CRUD ──

@pytest.mark.asyncio
async def test_create_course(client):
    resp = await client.post("/api/courses/", json={"name": "Test Course", "description": "Unit test"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Course"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_courses(client):
    create_resp = await client.post("/api/courses/", json={"name": "List Course", "description": "for list"})
    assert create_resp.status_code == 201
    resp = await client.get("/api/courses/")
    assert resp.status_code == 200
    courses = resp.json()
    assert isinstance(courses, list)
    assert len(courses) >= 1


@pytest.mark.asyncio
async def test_get_course(client):
    create_resp = await client.post("/api/courses/", json={"name": "Get Course", "description": "for get"})
    assert create_resp.status_code == 201
    cid = create_resp.json()["id"]
    resp = await client.get(f"/api/courses/{cid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == cid


@pytest.mark.asyncio
async def test_get_course_not_found(client):
    resp = await client.get("/api/courses/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_content_tree_empty(client):
    create_resp = await client.post("/api/courses/", json={"name": "Tree Course", "description": "for tree"})
    assert create_resp.status_code == 201
    cid = create_resp.json()["id"]
    resp = await client.get(f"/api/courses/{cid}/content-tree")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Preferences ──

@pytest.mark.asyncio
async def test_set_preference(client):
    resp = await client.post("/api/preferences/", json={
        "dimension": "note_format",
        "value": "table",
        "scope": "global",
    })
    assert resp.status_code in (200, 201)


@pytest.mark.asyncio
async def test_list_preferences(client):
    resp = await client.get("/api/preferences/")
    assert resp.status_code == 200
    prefs = resp.json()
    assert isinstance(prefs, list)


@pytest.mark.asyncio
async def test_resolve_preferences(client):
    resp = await client.get("/api/preferences/resolve")
    assert resp.status_code == 200
    data = resp.json()
    # Should contain system defaults at minimum
    assert isinstance(data, dict)


# ── Upload validation ──

@pytest.mark.asyncio
async def test_upload_invalid_course_id(client):
    resp = await client.post(
        "/api/content/upload",
        data={"course_id": "not-a-uuid"},
        files={"file": ("test.pdf", b"fake content", "application/pdf")},
    )
    assert resp.status_code in (400, 422)


# ── Auth endpoints ──

@pytest.mark.asyncio
async def test_auth_register_and_login(client):
    """Test full auth flow: register → login → access protected endpoint."""
    # Register
    resp = await client.post("/api/auth/register", json={
        "email": TEST_EMAIL,
        "password": "securepass123",
        "name": "Test User",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == TEST_EMAIL

    # Login
    resp = await client.post("/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": "securepass123",
    })
    assert resp.status_code == 200
    tokens = resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens

    # Refresh
    resp = await client.post("/api/auth/refresh", json={
        "refresh_token": tokens["refresh_token"],
    })
    assert resp.status_code == 200
    new_tokens = resp.json()
    assert "access_token" in new_tokens


@pytest.mark.asyncio
async def test_auth_duplicate_email(client):
    dup_email = f"dup-{uuid.uuid4().hex[:8]}@opentutor.dev"
    first = await client.post("/api/auth/register", json={
        "email": dup_email,
        "password": "securepass123",
    })
    assert first.status_code == 201

    resp = await client.post("/api/auth/register", json={
        "email": dup_email,
        "password": "anotherpass123",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_auth_wrong_password(client):
    resp = await client.post("/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


# ── Cleanup ──

@pytest.mark.asyncio
async def test_delete_course(client):
    create_resp = await client.post("/api/courses/", json={"name": "Delete Course", "description": "for delete"})
    assert create_resp.status_code == 201
    cid = create_resp.json()["id"]
    resp = await client.delete(f"/api/courses/{cid}")
    assert resp.status_code == 204
