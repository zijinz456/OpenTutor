"""Regression tests for the browser tool's outbound navigation sandbox."""

from types import SimpleNamespace
from typing import ClassVar

import pytest

from services.browser import automation


class _Route:
    def __init__(self) -> None:
        self.action = None

    async def continue_(self) -> None:
        self.action = "continue"

    async def abort(self, reason: str) -> None:
        self.action = ("abort", reason)


class _SyncRoute:
    def __init__(self) -> None:
        self.action = None

    def continue_(self) -> None:
        self.action = "continue"

    def abort(self, reason: str) -> None:
        self.action = ("abort", reason)


@pytest.mark.asyncio
async def test_browser_route_aborts_private_redirect_target(monkeypatch):
    async def reject_private(url: str) -> None:
        if "127.0.0.1" in url:
            raise ValueError("private address")

    monkeypatch.setattr(automation, "_validate_public_url", reject_private)
    route = _Route()

    await automation._guard_browser_request(
        route, SimpleNamespace(url="http://127.0.0.1/admin")
    )

    assert route.action == ("abort", "blockedbyclient")


@pytest.mark.asyncio
async def test_browser_route_allows_public_and_in_page_resources(monkeypatch):
    checked = []

    async def accept_public(url: str) -> None:
        checked.append(url)

    monkeypatch.setattr(automation, "_validate_public_url", accept_public)

    public = _Route()
    await automation._guard_browser_request(
        public, SimpleNamespace(url="https://example.com/app.js")
    )
    inline = _Route()
    await automation._guard_browser_request(
        inline, SimpleNamespace(url="data:text/plain,ok")
    )

    assert public.action == "continue"
    assert inline.action == "continue"
    assert checked == ["https://example.com/app.js"]


def test_scrapling_route_aborts_private_redirect_target(monkeypatch):
    def validate(url: str) -> str:
        if "127.0.0.1" in url:
            raise ValueError("private address")
        return url

    monkeypatch.setattr("libs.url_validation.validate_url", validate)
    route = _SyncRoute()

    automation._guard_scrapling_request(
        route, SimpleNamespace(url="http://127.0.0.1/admin")
    )

    assert route.action == ("abort", "blockedbyclient")


@pytest.mark.asyncio
async def test_http_redirect_is_validated_before_following(monkeypatch):
    requested = []
    validated = []

    class _Response:
        status_code = 302
        is_redirect = True
        headers: ClassVar = {"location": "http://127.0.0.1/metadata"}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, cookies=None):
            requested.append((url, cookies))
            return _Response()

    async def validate(url: str) -> None:
        validated.append(url)
        if "127.0.0.1" in url:
            raise ValueError("private address")

    monkeypatch.setattr(automation, "_validate_public_url", validate)
    monkeypatch.setattr("httpx.AsyncClient", lambda **_kwargs: _Client())

    assert (
        await automation.fetch_with_httpx("https://example.com", {"session": "x"})
        is None
    )
    assert requested == [("https://example.com", {"session": "x"})]
    assert validated == ["https://example.com", "http://127.0.0.1/metadata"]
