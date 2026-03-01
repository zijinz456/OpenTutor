"""Database engine and session management."""

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from config import settings

_TESTING = bool(os.environ.get("PYTEST_VERSION") or os.environ.get("PYTEST_CURRENT_TEST"))
_engine_kwargs = {"echo": False, "pool_pre_ping": not _TESTING}
if _TESTING:
    _engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(settings.database_url, **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


import models  # noqa: E402,F401  # Register ORM models with Base.metadata
