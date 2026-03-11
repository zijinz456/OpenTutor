"""Verify SQLite WAL mode and pragma configuration."""

import asyncio
import pytest
from sqlalchemy import text


def test_sqlite_wal_configured():
    """WAL mode should be enabled when using SQLite."""
    from database import engine, is_sqlite

    if not is_sqlite():
        pytest.skip("Not using SQLite")

    async def _check():
        async with engine.connect() as conn:
            result = await conn.execute(text("PRAGMA journal_mode"))
            mode = result.scalar()
            assert mode == "wal", f"Expected WAL mode, got {mode}"

            result = await conn.execute(text("PRAGMA foreign_keys"))
            fk = result.scalar()
            assert fk == 1, "foreign_keys should be ON"

    asyncio.run(_check())
