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

os.environ.setdefault("PYTEST_VERSION", "1")
os.environ.setdefault("DISABLE_RATE_LIMIT", "1")

# ``apps/api`` is two levels up from this conftest:
# apps/api/tests/conftest.py -> apps/api
API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)
