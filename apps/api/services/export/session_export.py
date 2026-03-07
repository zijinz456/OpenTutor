"""Session state export to portable SQLite file.

Exports user's learning data (memories, preferences, progress, KV store,
tool calls, chat messages) to a standalone SQLite file for backup or transfer.

Reads from the application database via SQLAlchemy async queries and writes
the results into a self-contained SQLite file that can be downloaded.
"""

import json
import logging
import os
import sqlite3
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQLite schema DDL
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT,
    memory_type TEXT,
    category TEXT,
    summary TEXT,
    importance REAL,
    access_count INTEGER,
    source_message TEXT,
    metadata_json TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS preferences (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT,
    scope TEXT,
    scene_type TEXT,
    dimension TEXT,
    value TEXT,
    source TEXT,
    confidence REAL,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS progress (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT,
    content_node_id TEXT,
    status TEXT,
    mastery_score REAL,
    time_spent_minutes INTEGER,
    review_count INTEGER,
    quiz_attempts INTEGER,
    quiz_correct INTEGER,
    gap_type TEXT,
    next_review_at TEXT,
    ease_factor REAL,
    interval_days INTEGER,
    fsrs_difficulty REAL,
    fsrs_stability REAL,
    fsrs_reps INTEGER,
    fsrs_lapses INTEGER,
    fsrs_state TEXT,
    last_studied_at TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS kv_store (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT,
    namespace TEXT,
    key TEXT,
    value_json TEXT,
    version INTEGER,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    user_id TEXT NOT NULL,
    course_id TEXT,
    agent_name TEXT,
    tool_name TEXT,
    status TEXT,
    error_message TEXT,
    duration_ms REAL,
    iteration INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    course_id TEXT,
    role TEXT,
    content TEXT,
    metadata_json TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS export_metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _build_course_filter(
    course_id: uuid.UUID | None,
    course_col: str = "course_id",
) -> tuple[str, dict]:
    """Return (SQL fragment, params dict) for optional course filtering."""
    if course_id is not None:
        return f"AND {course_col} = :course_id", {"course_id": str(course_id)}
    return "", {}


async def _export_table(
    db: AsyncSession,
    conn: sqlite3.Connection,
    *,
    query: str,
    params: dict,
    sqlite_table: str,
    columns: list[str],
) -> int:
    """Run a query and insert results into the SQLite table.

    Returns the number of rows exported.
    """
    result = await db.execute(text(query), params)
    rows = result.fetchall()
    if not rows:
        return 0

    placeholders = ", ".join(["?"] * len(columns))
    col_names = ", ".join(columns)
    insert_sql = f"INSERT OR IGNORE INTO {sqlite_table} ({col_names}) VALUES ({placeholders})"

    cursor = conn.cursor()
    for row in rows:
        values = []
        for val in row:
            if isinstance(val, uuid.UUID):
                values.append(str(val))
            elif isinstance(val, dict):
                values.append(json.dumps(val))
            elif val is None:
                values.append(None)
            else:
                values.append(str(val))
        cursor.execute(insert_sql, values)

    return len(rows)


async def export_session_state(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> Path:
    """Export user session state to a SQLite file.

    Creates a temporary SQLite file containing:
    - memories: conversation_memories
    - preferences: user_preferences
    - progress: learning_progress records
    - kv_store: agent_kv entries
    - tool_calls: tool_call_events log
    - chat_messages: recent chat history (via chat_sessions join)

    Args:
        db: Async SQLAlchemy session connected to the application database.
        user_id: The user whose data to export.
        course_id: Optional course filter. When provided, only data
                   associated with that course is exported.

    Returns:
        Path to the created SQLite file (caller is responsible for cleanup).
    """
    fd, filepath = tempfile.mkstemp(
        suffix=".sqlite",
        prefix=f"opentutor_export_{user_id}_",
    )
    # Close the raw fd; sqlite3.connect will reopen.
    os.close(fd)

    sqlite_conn = sqlite3.connect(filepath)
    try:
        sqlite_conn.executescript(_SQLITE_SCHEMA)

        base_params: dict = {"user_id": str(user_id)}
        course_frag, course_params = _build_course_filter(course_id)
        params = {**base_params, **course_params}

        counts: dict[str, int] = {}

        # ---- memories (conversation_memories) ----
        try:
            n = await _export_table(
                db,
                sqlite_conn,
                query=f"""
                    SELECT id, user_id, course_id, memory_type, category,
                           summary, importance, access_count, source_message,
                           metadata_json, created_at, updated_at
                    FROM conversation_memories
                    WHERE user_id = :user_id {course_frag}
                    ORDER BY created_at
                """,
                params=params,
                sqlite_table="memories",
                columns=[
                    "id", "user_id", "course_id", "memory_type", "category",
                    "summary", "importance", "access_count", "source_message",
                    "metadata_json", "created_at", "updated_at",
                ],
            )
            counts["memories"] = n
        except Exception as exc:
            logger.exception("Skipping memories export (table may not exist)")
            counts["memories"] = 0

        # ---- preferences (user_preferences) ----
        try:
            n = await _export_table(
                db,
                sqlite_conn,
                query=f"""
                    SELECT id, user_id, course_id, scope, scene_type,
                           dimension, value, source, confidence,
                           created_at, updated_at
                    FROM user_preferences
                    WHERE user_id = :user_id {course_frag}
                    ORDER BY created_at
                """,
                params=params,
                sqlite_table="preferences",
                columns=[
                    "id", "user_id", "course_id", "scope", "scene_type",
                    "dimension", "value", "source", "confidence",
                    "created_at", "updated_at",
                ],
            )
            counts["preferences"] = n
        except Exception as exc:
            logger.exception("Skipping preferences export (table may not exist)")
            counts["preferences"] = 0

        # ---- progress (learning_progress) ----
        try:
            n = await _export_table(
                db,
                sqlite_conn,
                query=f"""
                    SELECT id, user_id, course_id, content_node_id,
                           status, mastery_score, time_spent_minutes,
                           review_count, quiz_attempts, quiz_correct,
                           gap_type, next_review_at, ease_factor,
                           interval_days, fsrs_difficulty, fsrs_stability,
                           fsrs_reps, fsrs_lapses, fsrs_state,
                           last_studied_at, created_at, updated_at
                    FROM learning_progress
                    WHERE user_id = :user_id {course_frag}
                    ORDER BY created_at
                """,
                params=params,
                sqlite_table="progress",
                columns=[
                    "id", "user_id", "course_id", "content_node_id",
                    "status", "mastery_score", "time_spent_minutes",
                    "review_count", "quiz_attempts", "quiz_correct",
                    "gap_type", "next_review_at", "ease_factor",
                    "interval_days", "fsrs_difficulty", "fsrs_stability",
                    "fsrs_reps", "fsrs_lapses", "fsrs_state",
                    "last_studied_at", "created_at", "updated_at",
                ],
            )
            counts["progress"] = n
        except Exception as exc:
            logger.exception("Skipping progress export (table may not exist)")
            counts["progress"] = 0

        # ---- kv_store (agent_kv) ----
        try:
            n = await _export_table(
                db,
                sqlite_conn,
                query=f"""
                    SELECT id, user_id, course_id, namespace, key,
                           value_json, version, created_at, updated_at
                    FROM agent_kv
                    WHERE user_id = :user_id {course_frag}
                    ORDER BY created_at
                """,
                params=params,
                sqlite_table="kv_store",
                columns=[
                    "id", "user_id", "course_id", "namespace", "key",
                    "value_json", "version", "created_at", "updated_at",
                ],
            )
            counts["kv_store"] = n
        except Exception as exc:
            logger.exception("Skipping kv_store export (table may not exist)")
            counts["kv_store"] = 0

        # ---- tool_calls (tool_call_events) ----
        try:
            tool_call_course_frag = course_frag
            n = await _export_table(
                db,
                sqlite_conn,
                query=f"""
                    SELECT id, session_id, user_id, course_id,
                           agent_name, tool_name, status, error_message,
                           duration_ms, iteration, created_at
                    FROM tool_call_events
                    WHERE user_id = :user_id {tool_call_course_frag}
                    ORDER BY created_at
                """,
                params=params,
                sqlite_table="tool_calls",
                columns=[
                    "id", "session_id", "user_id", "course_id",
                    "agent_name", "tool_name", "status", "error_message",
                    "duration_ms", "iteration", "created_at",
                ],
            )
            counts["tool_calls"] = n
        except Exception as exc:
            logger.exception("Skipping tool_calls export (table may not exist)")
            counts["tool_calls"] = 0

        # ---- chat_messages (chat_message_logs via chat_sessions) ----
        # Chat messages are linked to sessions, not directly to user_id.
        # We join through chat_sessions to filter by user (and optionally course).
        try:
            chat_course_frag = course_frag.replace("course_id", "cs.course_id") if course_frag else ""
            chat_params = {**base_params}
            if course_id is not None:
                chat_params["course_id"] = str(course_id)

            n = await _export_table(
                db,
                sqlite_conn,
                query=f"""
                    SELECT cml.id, cml.session_id, cs.course_id,
                           cml.role, cml.content, cml.metadata_json,
                           cml.created_at
                    FROM chat_message_logs cml
                    JOIN chat_sessions cs ON cs.id = cml.session_id
                    WHERE cs.user_id = :user_id {chat_course_frag}
                    ORDER BY cml.created_at
                """,
                params=chat_params,
                sqlite_table="chat_messages",
                columns=[
                    "id", "session_id", "course_id",
                    "role", "content", "metadata_json", "created_at",
                ],
            )
            counts["chat_messages"] = n
        except Exception as exc:
            logger.exception("Skipping chat_messages export (table may not exist)")
            counts["chat_messages"] = 0

        # ---- export metadata ----
        cursor = sqlite_conn.cursor()
        cursor.execute(
            "INSERT INTO export_metadata (key, value) VALUES (?, ?)",
            ("user_id", str(user_id)),
        )
        cursor.execute(
            "INSERT INTO export_metadata (key, value) VALUES (?, ?)",
            ("course_id", str(course_id) if course_id else "all"),
        )
        cursor.execute(
            "INSERT INTO export_metadata (key, value) VALUES (?, ?)",
            ("row_counts", json.dumps(counts)),
        )
        cursor.execute(
            "INSERT INTO export_metadata (key, value) VALUES (?, ?)",
            ("format_version", "1"),
        )

        sqlite_conn.commit()
        logger.info(
            "Session export complete for user=%s course=%s: %s",
            user_id,
            course_id or "all",
            counts,
        )
    except Exception:
        sqlite_conn.close()
        # Clean up the file on failure
        try:
            os.unlink(filepath)
        except OSError:
            pass
        raise
    finally:
        sqlite_conn.close()

    return Path(filepath)
