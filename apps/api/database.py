"""Database engine and session management.

Supports both PostgreSQL (production) and SQLite (lightweight local mode).
The backend is selected automatically based on the DATABASE_URL scheme.
"""

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, StaticPool

from config import settings

_TESTING = bool(os.environ.get("PYTEST_VERSION") or os.environ.get("PYTEST_CURRENT_TEST"))

# Detect database backend from URL scheme
_is_sqlite = settings.database_url.startswith("sqlite")

_engine_kwargs: dict = {"echo": False}

if _is_sqlite:
    # SQLite: use StaticPool for single-connection async (aiosqlite)
    _engine_kwargs["poolclass"] = StaticPool
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
elif _TESTING:
    _engine_kwargs["pool_pre_ping"] = False
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_size"] = 20
    _engine_kwargs["max_overflow"] = 10

engine = create_async_engine(settings.database_url, **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def is_sqlite() -> bool:
    """Return True if the database backend is SQLite."""
    return _is_sqlite


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


import models  # noqa: E402,F401  # Register ORM models with Base.metadata
