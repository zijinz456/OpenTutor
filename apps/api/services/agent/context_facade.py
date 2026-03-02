"""Unified facade for agent subsystem access.

Wraps KV store, memory recall, progress tracking, and tutor notes
into a single clean interface that agents can use without importing
multiple service modules.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AgentContextFacade:
    """Convenience wrapper providing unified access to agent subsystems.

    Usage:
        facade = AgentContextFacade(ctx, db)
        notes = await facade.get_notes()
        await facade.kv_set("state", "current_topic", {"topic": "calculus"})
    """

    def __init__(self, ctx: Any, db: AsyncSession):
        self._ctx = ctx
        self._db = db

    # ── KV Store ──

    async def kv_get(self, namespace: str, key: str) -> dict | None:
        """Fetch a single KV entry. Returns value_json or None."""
        from services.agent.kv_store import kv_get

        return await kv_get(
            self._db,
            self._ctx.user_id,
            namespace,
            key,
            course_id=self._ctx.course_id,
        )

    async def kv_set(self, namespace: str, key: str, value: Any) -> None:
        """Upsert a KV entry."""
        from services.agent.kv_store import kv_set

        await kv_set(
            self._db,
            self._ctx.user_id,
            namespace,
            key,
            value,
            course_id=self._ctx.course_id,
        )

    async def kv_list(self, namespace: str) -> list[dict]:
        """List all KV entries in a namespace."""
        from services.agent.kv_store import kv_list

        return await kv_list(
            self._db,
            self._ctx.user_id,
            namespace,
            course_id=self._ctx.course_id,
        )

    async def kv_delete(self, namespace: str, key: str) -> bool:
        """Delete a KV entry. Returns True if something was deleted."""
        from services.agent.kv_store import kv_delete

        return await kv_delete(
            self._db,
            self._ctx.user_id,
            namespace,
            key,
            course_id=self._ctx.course_id,
        )

    # ── Memory ──

    async def recall(self, query: str, limit: int = 5) -> list[dict]:
        """Hybrid BM25 + vector search over conversation memories.

        Returns a list of memory dicts with keys like 'summary',
        'memory_type', 'importance', 'hybrid_score', etc.
        """
        try:
            from services.memory.pipeline import retrieve_memories

            return await retrieve_memories(
                self._db,
                self._ctx.user_id,
                query,
                course_id=self._ctx.course_id,
                limit=limit,
            )
        except Exception as e:
            logger.warning("Memory recall failed: %s", e)
            return []

    async def remember(
        self,
        user_message: str,
        assistant_response: str,
    ) -> list:
        """Encode a conversation turn into atomic MemCell memories.

        This runs the full 3-stage memory pipeline (encode stage).
        Returns the list of created ConversationMemory objects (usually 0-2).
        """
        try:
            from services.memory.pipeline import encode_memory

            return await encode_memory(
                self._db,
                self._ctx.user_id,
                self._ctx.course_id,
                user_message,
                assistant_response,
            )
        except Exception as e:
            logger.warning("Memory encoding failed: %s", e)
            return []

    # ── Tutor Notes (via KV store) ──

    async def get_notes(self) -> dict | None:
        """Get tutor notes for current student+course from KV store."""
        return await self.kv_get("tutor_notes", "notes")

    async def set_notes(self, notes: str) -> None:
        """Set tutor notes for current student+course via KV store."""
        await self.kv_set("tutor_notes", "notes", {"notes": notes})

    # ── Progress ──

    async def get_progress(self) -> dict | None:
        """Get overall course progress summary for the current student+course.

        Returns a dict with keys: total_nodes, mastered, reviewed,
        in_progress, not_started, total_study_minutes, average_mastery,
        completion_percent, gap_type_breakdown, etc.
        """
        try:
            from services.progress.tracker import get_course_progress

            return await get_course_progress(
                self._db,
                self._ctx.user_id,
                self._ctx.course_id,
            )
        except Exception as e:
            logger.warning("Progress retrieval failed: %s", e)
            return None
