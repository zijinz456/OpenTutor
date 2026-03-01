import sys
import types
import uuid
from types import SimpleNamespace

import pytest

from libs.exceptions import ValidationError
from models.scrape import AuthSession
from routers.canvas import canvas_login, canvas_sync, CanvasLoginRequest, CanvasSyncRequest


class _FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeDB:
    def __init__(self, execute_results=None):
        self.execute_results = list(execute_results or [])
        self.added = []

    async def execute(self, _stmt):
        if not self.execute_results:
            return _FakeResult()
        return self.execute_results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None


def _user():
    return SimpleNamespace(id=uuid.uuid4())


def _mock_playwright(monkeypatch):
    class _Browser:
        async def close(self):
            return None

    class _Chromium:
        async def launch(self, headless=True):
            return _Browser()

    class _Playwright:
        chromium = _Chromium()

    class _CM:
        async def __aenter__(self):
            return _Playwright()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async_api = types.ModuleType("playwright.async_api")
    async_api.async_playwright = lambda: _CM()
    playwright_pkg = types.ModuleType("playwright")
    playwright_pkg.async_api = async_api
    monkeypatch.setitem(sys.modules, "playwright", playwright_pkg)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)


@pytest.mark.asyncio
async def test_canvas_login_creates_auth_session_without_login_actions(monkeypatch):
    _mock_playwright(monkeypatch)

    async def _ok_reauth(*args, **kwargs):
        return True

    monkeypatch.setattr("services.browser.session_manager.SessionManager.re_authenticate", _ok_reauth)
    db = _FakeDB(execute_results=[_FakeResult(scalar=None)])
    user = _user()

    resp = await canvas_login(
        body=CanvasLoginRequest(
            canvas_url="https://canvas.example.edu",
            username="alice",
            password="secret",
        ),
        user=user,
        db=db,
    )

    assert resp["status"] == "ok"
    sessions = [x for x in db.added if isinstance(x, AuthSession)]
    assert sessions
    assert sessions[0].login_actions is None


@pytest.mark.asyncio
async def test_canvas_sync_rejects_token_mode():
    with pytest.raises(ValidationError) as e:
        await canvas_sync(
            body=CanvasSyncRequest(
                canvas_url="https://canvas.example.edu",
                api_token="abc",
            ),
            user=_user(),
            db=_FakeDB(),
        )
    assert e.value.status == 422
