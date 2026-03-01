import uuid
import types
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from libs.exceptions import NotFoundError

from models.scrape import ScrapeSource
from routers.scrape import (
    create_scrape_source,
    update_scrape_source,
    delete_scrape_source,
    scrape_now,
    validate_auth_session,
    auth_login,
)
from schemas.scrape import ScrapeSourceCreate, ScrapeSourceUpdate, AuthLoginRequest


class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeResult:
    def __init__(self, scalar=None, scalars=None):
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return _FakeScalars(self._scalars)


class _FakeDB:
    def __init__(self, execute_results=None):
        self.execute_results = list(execute_results or [])
        self.added = []
        self.deleted = []

    async def execute(self, _stmt):
        if not self.execute_results:
            return _FakeResult()
        return self.execute_results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


def _user():
    return SimpleNamespace(id=uuid.uuid4())


def test_scrape_source_create_rejects_invalid_source_type():
    with pytest.raises(ValidationError):
        ScrapeSourceCreate(
            url="https://example.com",
            course_id=uuid.uuid4(),
            source_type="canavs",  # typo
        )


@pytest.mark.asyncio
async def test_create_scrape_source_course_not_found_404():
    db = _FakeDB(execute_results=[_FakeResult(scalar=None)])
    body = ScrapeSourceCreate(
        url="https://example.com/page",
        course_id=uuid.uuid4(),
        requires_auth=False,
    )

    with pytest.raises(NotFoundError) as e:
        await create_scrape_source(body=body, user=_user(), db=db)

    assert e.value.status == 404


@pytest.mark.asyncio
async def test_create_scrape_source_requires_auth_false_clears_auth_fields():
    db = _FakeDB(execute_results=[_FakeResult(scalar=SimpleNamespace(id=uuid.uuid4()))])
    user = _user()
    body = ScrapeSourceCreate(
        url="https://example.com/page",
        course_id=uuid.uuid4(),
        requires_auth=False,
        auth_domain="example.com",
        session_name="../unsafe",
    )

    source = await create_scrape_source(body=body, user=user, db=db)

    assert isinstance(source, ScrapeSource)
    assert source.requires_auth is False
    assert source.auth_domain is None
    assert source.session_name is None


@pytest.mark.asyncio
async def test_create_scrape_source_requires_auth_derives_domain_and_session_name():
    db = _FakeDB(execute_results=[_FakeResult(scalar=SimpleNamespace(id=uuid.uuid4()))])
    user = _user()
    body = ScrapeSourceCreate(
        url="https://sub.example.com/path",
        course_id=uuid.uuid4(),
        requires_auth=True,
    )

    source = await create_scrape_source(body=body, user=user, db=db)

    assert source.auth_domain == "sub.example.com"
    assert user.id.hex in source.session_name
    assert "." not in source.session_name
    assert "/" not in source.session_name


@pytest.mark.asyncio
async def test_create_scrape_source_canvas_url_stays_user_configured():
    db = _FakeDB(execute_results=[_FakeResult(scalar=SimpleNamespace(id=uuid.uuid4()))])
    user = _user()
    body = ScrapeSourceCreate(
        url="https://canvas.example.edu/courses/1",
        course_id=uuid.uuid4(),
        source_type="generic",
        requires_auth=False,
    )

    source = await create_scrape_source(body=body, user=user, db=db)

    assert source.source_type == "generic"
    assert source.requires_auth is False


@pytest.mark.asyncio
async def test_update_scrape_source_not_found_404():
    db = _FakeDB(execute_results=[_FakeResult(scalar=None)])

    with pytest.raises(NotFoundError) as e:
        await update_scrape_source(
            source_id=uuid.uuid4(),
            body=ScrapeSourceUpdate(label="x"),
            user=_user(),
            db=db,
        )

    assert e.value.status == 404


@pytest.mark.asyncio
async def test_update_scrape_source_turn_off_auth_clears_fields():
    existing = ScrapeSource(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        url="https://example.com/private",
        requires_auth=True,
        auth_domain="example.com",
        session_name="abc",
    )
    db = _FakeDB(execute_results=[_FakeResult(scalar=existing)])

    updated = await update_scrape_source(
        source_id=uuid.uuid4(),
        body=ScrapeSourceUpdate(requires_auth=False),
        user=SimpleNamespace(id=existing.user_id),
        db=db,
    )

    assert updated.requires_auth is False
    assert updated.auth_domain is None
    assert updated.session_name is None


@pytest.mark.asyncio
async def test_delete_scrape_source_not_found_404():
    db = _FakeDB(execute_results=[_FakeResult(scalar=None)])

    with pytest.raises(NotFoundError) as e:
        await delete_scrape_source(source_id=uuid.uuid4(), user=_user(), db=db)

    assert e.value.status == 404


@pytest.mark.asyncio
async def test_scrape_now_not_found_404():
    db = _FakeDB(execute_results=[_FakeResult(scalar=None)])

    with pytest.raises(NotFoundError) as e:
        await scrape_now(source_id=uuid.uuid4(), user=_user(), db=db)

    assert e.value.status == 404


@pytest.mark.asyncio
async def test_validate_auth_session_not_found_404():
    db = _FakeDB(execute_results=[_FakeResult(scalar=None)])

    with pytest.raises(NotFoundError) as e:
        await validate_auth_session(session_name="../bad", user=_user(), db=db)

    assert e.value.status == 404


def _mock_playwright_module(monkeypatch):
    class _Browser:
        async def close(self):
            return None

    class _Chromium:
        async def launch(self, headless=True):
            return _Browser()

    class _Playwright:
        chromium = _Chromium()

    class _AsyncPlaywrightCM:
        async def __aenter__(self):
            return _Playwright()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async_api = types.ModuleType("playwright.async_api")
    async_api.async_playwright = lambda: _AsyncPlaywrightCM()
    playwright_pkg = types.ModuleType("playwright")
    playwright_pkg.async_api = async_api
    monkeypatch.setitem(sys.modules, "playwright", playwright_pkg)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)


@pytest.mark.asyncio
async def test_auth_login_returns_401_when_reauth_fails(monkeypatch):
    _mock_playwright_module(monkeypatch)

    async def _fail_reauth(*args, **kwargs):
        return False

    monkeypatch.setattr(
        "services.browser.session_manager.SessionManager.re_authenticate",
        _fail_reauth,
    )
    db = _FakeDB()
    body = AuthLoginRequest(
        domain="example.com",
        login_url="https://example.com/login",
        actions=[{"type": "fill", "selector": "#u", "value": "a"}],
    )

    with pytest.raises(HTTPException) as e:
        await auth_login(body=body, user=_user(), db=db)

    assert e.value.status_code == 401


@pytest.mark.asyncio
async def test_auth_login_creates_new_session_record(monkeypatch):
    _mock_playwright_module(monkeypatch)

    async def _ok_reauth(*args, **kwargs):
        return True

    monkeypatch.setattr(
        "services.browser.session_manager.SessionManager.re_authenticate",
        _ok_reauth,
    )

    db = _FakeDB(execute_results=[_FakeResult(scalar=None)])
    user = _user()
    body = AuthLoginRequest(
        domain="sub.example.com",
        login_url="https://sub.example.com/login",
        check_url="https://sub.example.com/dashboard",
        actions=[{"type": "fill", "selector": "#u", "value": "a"}],
    )

    session = await auth_login(body=body, user=user, db=db)

    assert session.user_id == user.id
    assert session.domain == "sub.example.com"
    assert user.id.hex in session.session_name
