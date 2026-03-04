"""LangGraph checkpoint persistence — PostgreSQL or SQLite.

Provides crash-safe, cross-session workflow persistence for all LangGraph
StateGraphs.  Automatically selects the backend based on DATABASE_URL.

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
from database import is_sqlite

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


def _get_sqlite_path() -> str:
    """Extract the file path from a SQLite URL for LangGraph's SQLite saver."""
    url = settings.database_url
    # sqlite+aiosqlite:///path/to/db  ->  path/to/db
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///", "sqlite+aiosqlite://"):
        if url.startswith(prefix):
            return url[len(prefix):] or ":memory:"
    return url


async def setup_checkpointer():
    """Initialise the checkpoint backend.

    Called once during app startup.  Creates checkpoint tables if needed.
    """
    global _checkpointer, _pool

    if is_sqlite():
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            db_path = _get_sqlite_path()
            _checkpointer = AsyncSqliteSaver.from_conn_string(db_path)
            await _checkpointer.setup()
            logger.info("LangGraph checkpoint persistence initialised (SQLite)")
        except ImportError:
            logger.warning(
                "langgraph-checkpoint-sqlite not installed — "
                "workflows will run without persistence. "
                "Install with: pip install langgraph-checkpoint-sqlite"
            )
            _checkpointer = None
        except Exception as exc:
            logger.warning(
                "LangGraph SQLite checkpoint init failed: %s", exc
            )
            _checkpointer = None
        return

    # PostgreSQL path (original implementation)
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
