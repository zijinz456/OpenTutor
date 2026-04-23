"""One-shot helper: create_all() against the configured DATABASE_URL.

Used when the API container can't boot (e.g. unrelated import error in
a router) but we still need the schema up-to-date for a seed script
run. Idempotent — ``create_all`` skips tables that already exist.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parent.parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from database import Base, engine  # noqa: E402
import models  # noqa: E402,F401


async def _run() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("schema ensured (create_all)")


if __name__ == "__main__":
    asyncio.run(_run())
