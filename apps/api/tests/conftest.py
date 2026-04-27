"""Pytest bootstrap for tests that live under ``apps/api/tests/``.

Mirrors the root-level ``tests/conftest.py`` so these tests can be invoked
directly from inside the api container (``docker exec opentutor-api pytest
apps/api/tests/...``), where the repo root is not mounted and only
``apps/api`` is available as ``/app``.

If we're already running from the repo root (``sys.path`` already includes
``apps/api``), the insert is a no-op.
"""

import os
import sys
from typing import Any

import pytest

os.environ.setdefault("PYTEST_VERSION", "1")
os.environ.setdefault("DISABLE_RATE_LIMIT", "1")

# ``apps/api`` is two levels up from this conftest:
# apps/api/tests/conftest.py -> apps/api
API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)


@pytest.fixture(autouse=True)
def _reset_sse_starlette_singleton():
    """Defeat ``sse_starlette.AppStatus.should_exit_event`` leaking
    between pytest-asyncio function-scoped event loops.

    ``sse_starlette/sse.py`` keeps ``AppStatus`` as a class-level
    singleton; the first ``EventSourceResponse`` instantiates
    ``anyio.Event()`` against the active event loop, then every
    subsequent test (running on a fresh per-function loop) reuses the
    bound Event and explodes with ``RuntimeError: <Event> is bound to
    a different event loop``.

    Resetting ``should_exit_event = None`` and ``should_exit = False``
    before/after each test forces re-instantiation against the current
    loop. Idempotent + cheap — runs for every test in the suite, sync
    or async; sync tests never touch the Event so the reset is a no-op
    for them. See ``docs/qa/g6_failing_tests_triage.md`` for the full
    root-cause analysis (8 failures all collapsed to this one source).
    """

    # Hold the class as ``Any`` so we can write the singleton fields
    # via a uniform ``setattr`` whether sse_starlette imported or not
    # (it's genuinely unavailable in some local host venvs). Importing
    # under a different name avoids the static-checker shadowing
    # complaint that fires when we write ``AppStatus = None`` against
    # an already-bound class identifier.
    app_status: Any = None
    try:
        from sse_starlette.sse import AppStatus as _AppStatus

        app_status = _AppStatus
    except ImportError:
        pass

    # Use ``setattr`` for the dynamic-attribute writes — sse_starlette
    # mutates ``should_exit_event`` at runtime but doesn't declare it
    # on the class type, so static checkers flag the dotted form.
    if app_status is not None:
        setattr(app_status, "should_exit_event", None)
        setattr(app_status, "should_exit", False)

    yield

    if app_status is not None:
        setattr(app_status, "should_exit_event", None)
        setattr(app_status, "should_exit", False)
