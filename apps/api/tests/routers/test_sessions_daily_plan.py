"""Router tests for `GET /api/sessions/daily-plan` bad-day strategy wiring."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock

import database as database_module
import pytest
import pytest_asyncio
import routers.sessions as sessions_router
from database import Base, get_db
from httpx import ASGITransport, AsyncClient
from main import app
from schemas.sessions import DailyPlan
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


@pytest_asyncio.fixture
async def client_with_db():
    fd, db_path = tempfile.mkstemp(prefix="opentutor-daily-router-", suffix=".db")
    os.close(fd)

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

    async def _override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    original_async_session = database_module.async_session
    database_module.async_session = test_session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)
    database_module.async_session = original_async_session
    await test_engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.mark.asyncio
async def test_daily_plan_easy_only_strategy_returns_200(
    client_with_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    select_mock = AsyncMock(
        return_value=DailyPlan(cards=[], size=0, reason="bad_day_empty")
    )
    freeze_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(sessions_router, "select_daily_plan", select_mock)
    monkeypatch.setattr(sessions_router, "active_frozen_problem_ids", freeze_mock)

    resp = await client_with_db.get(
        "/api/sessions/daily-plan?size=5&strategy=easy_only"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"cards": [], "size": 0, "reason": "bad_day_empty"}

    call = select_mock.await_args
    assert call.args[1] == 5
    assert call.kwargs["strategy"] == "easy_only"
    assert call.kwargs["excluded_ids"] == []


@pytest.mark.asyncio
async def test_daily_plan_rejects_internal_struggle_first_strategy(
    client_with_db,
) -> None:
    resp = await client_with_db.get(
        "/api/sessions/daily-plan?size=5&strategy=struggle_first"
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_daily_plan_rejects_invalid_strategy(
    client_with_db,
) -> None:
    resp = await client_with_db.get("/api/sessions/daily-plan?size=5&strategy=invalid")
    assert resp.status_code == 422
