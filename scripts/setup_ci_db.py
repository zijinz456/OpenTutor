"""Reusable CI database setup script.

Creates the opentutor role, database, and pgvector extension.
Used by all CI jobs that need a PostgreSQL database, eliminating
copy-pasted inline Python scripts.

Usage:
    python scripts/setup_ci_db.py [--host HOST] [--port PORT]
"""

import argparse
import asyncio
import asyncpg


async def setup_database(host: str = "127.0.0.1", port: int = 5432):
    conn = await asyncpg.connect(
        host=host,
        port=port,
        user="postgres",
        password="postgres",
        database="postgres",
        timeout=10,
    )
    role_exists = await conn.fetchval(
        "SELECT 1 FROM pg_roles WHERE rolname='opentutor'"
    )
    if not role_exists:
        await conn.execute("CREATE ROLE opentutor WITH LOGIN PASSWORD 'opentutor_dev'")
    db_exists = await conn.fetchval(
        "SELECT 1 FROM pg_database WHERE datname='opentutor'"
    )
    if not db_exists:
        await conn.execute("CREATE DATABASE opentutor OWNER opentutor")
    await conn.close()

    conn2 = await asyncpg.connect(
        host=host,
        port=port,
        user="postgres",
        password="postgres",
        database="opentutor",
        timeout=10,
    )
    await conn2.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await conn2.close()

    print(f"Database ready at {host}:{port}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    args = parser.parse_args()
    asyncio.run(setup_database(args.host, args.port))
