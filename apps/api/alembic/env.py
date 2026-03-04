"""Alembic environment for async SQLAlchemy."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import Base
from models import *  # noqa: F401, F403 — register all models
from config import settings as app_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use DATABASE_URL from app config (environment / .env) instead of hardcoded alembic.ini value
config.set_main_option("sqlalchemy.url", app_settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    # Guard: SQLite mode uses create_all(), not Alembic migrations
    db_url = config.get_main_option("sqlalchemy.url", "")
    if db_url.startswith("sqlite"):
        print("SQLite mode detected — migrations skipped (tables created via create_all() at startup).")
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
