"""LangGraph checkpoint persistence via PostgreSQL.

Provides crash-safe, cross-session workflow persistence for all LangGraph
StateGraphs.  Uses ``langgraph-checkpoint-postgres`` with the same database
connection string as the main application.

Usage in graph builders::

    from services.workflow.checkpoint import get_checkpointer

    checkpointer = get_checkpointer()
    graph = StateGraph(MyState)
    ...
    compiled = graph.compile(checkpointer=checkpointer)

Thread IDs follow the convention ``{user_id}:{course_id}:{workflow_name}``
so each user × course × workflow gets its own checkpoint lineage.
"""

import logging
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

_checkpointer: Optional[object] = None
_pool = None


def _get_sync_conninfo() -> str:
    """Convert asyncpg URL to psycopg-compatible connection string.

    The main app uses ``postgresql+asyncpg://...`` but psycopg needs
    ``postgresql://...`` (no driver prefix).
    """
    url = settings.database_url
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


async def setup_checkpointer():
    """Initialise the async PostgreSQL checkpointer.

    Called once during app startup.  Creates the checkpoint tables if they
    don't exist (idempotent).
    """
    global _checkpointer, _pool

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        conninfo = _get_sync_conninfo()
        _pool = AsyncConnectionPool(conninfo=conninfo, open=False)
        await _pool.open()

        _checkpointer = AsyncPostgresSaver(_pool)
        await _checkpointer.setup()

        logger.info("LangGraph checkpoint persistence initialised (PostgreSQL)")
    except Exception as exc:
        logger.warning(
            "LangGraph checkpoint init failed (workflows will run without persistence): %s",
            exc,
        )
        _checkpointer = None


async def teardown_checkpointer():
    """Close the checkpoint connection pool during shutdown."""
    global _checkpointer, _pool

    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            pass
    _checkpointer = None
    _pool = None


def get_checkpointer():
    """Return the initialised checkpointer, or ``None`` if unavailable.

    Graphs compiled with ``checkpointer=None`` work identically to before
    — they simply won't persist state across crashes.
    """
    return _checkpointer


def make_thread_id(
    user_id,
    course_id=None,
    workflow: str = "default",
) -> str:
    """Build a deterministic thread ID for checkpoint scoping."""
    course_part = str(course_id) if course_id else "global"
    return f"{user_id}:{course_part}:{workflow}"
