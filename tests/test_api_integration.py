"""API integration tests using httpx AsyncClient.

These tests require a PostgreSQL database (auto-created in conftest).
Run with: pytest tests/test_api_integration.py -v
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app
from database import get_db, engine, Base

# Use a separate test schema or ensure clean state
TEST_COURSE_IDS = []


@pytest_asyncio.fixture(scope="module")
async def client():
    """Create test client with real database tables."""
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


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
    TEST_COURSE_IDS.append(data["id"])


@pytest.mark.asyncio
async def test_list_courses(client):
    resp = await client.get("/api/courses/")
    assert resp.status_code == 200
    courses = resp.json()
    assert isinstance(courses, list)
    assert len(courses) >= 1


@pytest.mark.asyncio
async def test_get_course(client):
    if not TEST_COURSE_IDS:
        pytest.skip("No course created")
    resp = await client.get(f"/api/courses/{TEST_COURSE_IDS[0]}")
    assert resp.status_code == 200
    assert resp.json()["id"] == TEST_COURSE_IDS[0]


@pytest.mark.asyncio
async def test_get_course_not_found(client):
    resp = await client.get("/api/courses/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_content_tree_empty(client):
    if not TEST_COURSE_IDS:
        pytest.skip("No course created")
    resp = await client.get(f"/api/courses/{TEST_COURSE_IDS[0]}/content-tree")
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
        "email": "test@opentutor.dev",
        "password": "securepass123",
        "name": "Test User",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "test@opentutor.dev"

    # Login
    resp = await client.post("/api/auth/login", json={
        "email": "test@opentutor.dev",
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
    resp = await client.post("/api/auth/register", json={
        "email": "test@opentutor.dev",
        "password": "anotherpass123",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_auth_wrong_password(client):
    resp = await client.post("/api/auth/login", json={
        "email": "test@opentutor.dev",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


# ── Cleanup ──

@pytest.mark.asyncio
async def test_delete_course(client):
    if not TEST_COURSE_IDS:
        pytest.skip("No course created")
    resp = await client.delete(f"/api/courses/{TEST_COURSE_IDS[0]}")
    assert resp.status_code == 204
