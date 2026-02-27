import uuid

import pytest

from models.scrape import ScrapeSource
from routers.scrape import _default_session_name
from services.browser.session_manager import SessionManager
from services.scraper import runner


def test_session_name_normalization_blocks_path_segments():
    unsafe = "../a/b:c?d"
    normalized = SessionManager.normalize_session_name(unsafe)
    assert "/" not in normalized
    assert "." not in normalized
    assert normalized

    path = SessionManager.state_file(unsafe)
    assert path.parent.name == "sessions"
    assert path.name.endswith("_state.json")
    assert ".." not in str(path)


def test_auto_disable_source_after_max_failures(monkeypatch):
    source = ScrapeSource(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        url="https://example.com",
        enabled=True,
        consecutive_failures=runner.MAX_CONSECUTIVE_FAILURES,
    )
    called = {"notified": False}

    def _fake_notify(_source):
        called["notified"] = True

    monkeypatch.setattr(runner, "_notify_scrape_disabled", _fake_notify)
    runner._maybe_disable_source(source)

    assert source.enabled is False
    assert called["notified"] is True


def test_mark_auth_expired_notifies_only_on_first_transition(monkeypatch):
    source = ScrapeSource(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        url="https://example.com",
        enabled=True,
        last_status=None,
    )
    calls = {"count": 0}

    def _fake_notify(_source):
        calls["count"] += 1

    monkeypatch.setattr(runner, "_notify_auth_expired", _fake_notify)
    runner._mark_auth_expired(source)
    runner._mark_auth_expired(source)

    assert source.last_status == "auth_expired"
    assert calls["count"] == 1


def test_default_session_name_uses_full_user_id_and_is_safe():
    user_id = uuid.uuid4()
    name = _default_session_name(user_id, "sub.example.com")
    assert user_id.hex in name
    assert "." not in name
    assert "/" not in name


@pytest.mark.asyncio
async def test_scrape_single_preserves_auth_expired_status(monkeypatch):
    source = ScrapeSource(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        url="https://example.com/private",
        requires_auth=True,
        enabled=True,
    )
    now = runner.datetime.now(runner.timezone.utc)

    async def _fake_auth_fetch(_db, src):
        src.last_status = "auth_expired"
        return None

    monkeypatch.setattr(runner, "_authenticated_fetch", _fake_auth_fetch)

    class _FakeDB:
        async def flush(self):
            return None

    changed = await runner._scrape_single(_FakeDB(), source, now)
    assert changed is False
    assert source.last_status == "auth_expired"
    assert source.consecutive_failures == 1


@pytest.mark.asyncio
async def test_scrape_single_uses_generic_pipeline_even_for_canvas_source_type(monkeypatch):
    source = ScrapeSource(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        url="https://canvas.example.edu/courses/1/assignments",
        source_type="canvas",
        requires_auth=False,
        enabled=True,
    )
    now = runner.datetime.now(runner.timezone.utc)
    called = {"generic": False}

    async def _fake_cascade_fetch(_url):
        return "<html><body>new content</body></html>"

    async def _fake_generic(_db, _source, _content, _content_hash, _now):
        called["generic"] = True
        return True

    monkeypatch.setattr("services.browser.automation.cascade_fetch", _fake_cascade_fetch)
    monkeypatch.setattr(runner, "_process_generic_content", _fake_generic)

    class _FakeDB:
        async def flush(self):
            return None

    changed = await runner._scrape_single(_FakeDB(), source, now)
    assert changed is True
    assert called["generic"] is True
