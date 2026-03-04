"""SQLite lite mode integration tests.

Verify the full app works end-to-end with SQLite instead of PostgreSQL.
Covers: table creation, health check, course CRUD, chat (mock LLM), search.

NOTE: Must run in isolation — SQLAlchemy model classes bind to Base at import
time, so they cannot be safely reloaded after PG-mode tests already loaded them.
Run with:  pytest tests/test_sqlite_mode.py
"""

import os
import sys
import tempfile
import uuid

import pytest

# ── Must set env BEFORE any app imports ──

_tmp_dir = tempfile.mkdtemp(prefix="opentutor_test_")
_db_path = os.path.join(_tmp_dir, "test.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db_path}"
os.environ["SERVE_BUILTIN_UI"] = "true"
os.environ["LLM_REQUIRED"] = "false"
os.environ["APP_AUTO_CREATE_TABLES"] = "true"
os.environ["APP_AUTO_SEED_SYSTEM"] = "true"

# Ensure the API package is importable
api_dir = os.path.join(os.path.dirname(__file__), "..", "apps", "api")
sys.path.insert(0, os.path.abspath(api_dir))

# Skip entire module if database was already loaded with PG (stale Base).
_db_mod = sys.modules.get("database")
if _db_mod and hasattr(_db_mod, "_is_sqlite") and not _db_mod._is_sqlite:
    pytest.skip(
        "SQLite tests require isolated run: pytest tests/test_sqlite_mode.py",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
async def app():
    """Create the FastAPI app with SQLite backend."""
    from main import create_app
    from services.app_lifecycle import run_startup_hooks, run_shutdown_hooks

    application = create_app()
    await run_startup_hooks()
    yield application
    await run_shutdown_hooks()


@pytest.fixture(scope="module")
async def client(app):
    """Async test client for the SQLite-backed app."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Tests ──


@pytest.mark.anyio
async def test_database_is_sqlite():
    """Verify database.py detected SQLite backend."""
    from database import is_sqlite
    assert is_sqlite() is True


@pytest.mark.anyio
async def test_tables_created(app):
    """Verify create_all() successfully created core tables in SQLite."""
    from database import engine
    from sqlalchemy import text, inspect

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        tables = {row[0] for row in result.fetchall()}

    assert "users" in tables, f"Missing 'users' table. Found: {tables}"
    assert "courses" in tables
    assert "course_content_tree" in tables
    assert "conversation_memories" in tables
    assert "chat_sessions" in tables
    assert "chat_message_logs" in tables


@pytest.mark.anyio
async def test_health_endpoint(client):
    """Health check should return ok with SQLite."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok", f"Health not ok: {data}"
    assert data["schema"] == "ready"
    assert data["migration_required"] is False
    assert data["database"] == "connected"


@pytest.mark.anyio
async def test_builtin_ui_served(client):
    """Built-in UI should be served at /."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "OpenTutor" in resp.text
    assert "text/html" in resp.headers.get("content-type", "")


@pytest.mark.anyio
async def test_course_crud(client):
    """Create and list courses via API."""
    # Create (201 Created)
    resp = await client.post("/api/courses/", json={"name": "Test Course"})
    assert resp.status_code in (200, 201)
    course = resp.json()
    assert course["name"] == "Test Course"
    course_id = course["id"]

    # List
    resp = await client.get("/api/courses/")
    assert resp.status_code == 200
    courses = resp.json()
    names = [c["name"] for c in courses]
    assert "Test Course" in names

    # Get
    resp = await client.get(f"/api/courses/{course_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Test Course"


@pytest.mark.anyio
async def test_migration_inspector_sqlite():
    """Migration inspector should report ready for SQLite (no Alembic needed)."""
    from database import engine
    from services.migrations import inspect_database_migrations

    async with engine.connect() as conn:
        state = await conn.run_sync(inspect_database_migrations)

    assert state.migration_status == "ready"
    assert state.schema_ready is True
    assert state.migration_required is False
    assert state.alembic_version_present is False
