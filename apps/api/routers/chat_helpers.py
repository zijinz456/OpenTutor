"""Chat router helper functions — session management, persistence, serialization.

Extracted from chat.py to keep route handlers concise.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from libs.exceptions import NotFoundError
from models.chat_message import ChatMessageLog
from models.chat_session import ChatSession
from utils.serializers import serialize_model


def build_session_title(message: str) -> str:
    """Build a human-friendly title from the first user message."""
    normalized = " ".join(message.strip().split())
    if not normalized:
        return "New Chat"
    return normalized[:77] + "..." if len(normalized) > 80 else normalized


async def resolve_chat_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    scene_id: str | None,
    message: str,
    session_id: uuid.UUID | None,
) -> ChatSession:
    """Find an existing chat session or create a new one."""
    if session_id:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
                ChatSession.course_id == course_id,
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            raise NotFoundError("Chat session", session_id)
        if scene_id and session.scene_id != scene_id:
            session.scene_id = scene_id
        if not session.title:
            session.title = build_session_title(message)
        await db.flush()
        return session

    session = ChatSession(
        user_id=user_id,
        course_id=course_id,
        scene_id=scene_id,
        title=build_session_title(message),
    )
    db.add(session)
    await db.flush()
    return session


async def persist_chat_turn(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_message: str,
    assistant_message: str,
    assistant_metadata: dict | None = None,
) -> None:
    """Save a user/assistant message pair and update session timestamp."""
    if not assistant_message.strip():
        return
    db.add_all(
        [
            ChatMessageLog(session_id=session_id, role="user", content=user_message),
            ChatMessageLog(
                session_id=session_id,
                role="assistant",
                content=assistant_message,
                metadata_json=assistant_metadata,
            ),
        ]
    )
    await db.execute(
        update(ChatSession).where(ChatSession.id == session_id).values(updated_at=datetime.now(timezone.utc))
    )
    await db.commit()


def serialize_session(session: ChatSession, message_count: int) -> dict:
    """Serialize a ChatSession ORM object to a dict."""
    data = serialize_model(session, ["id", "course_id", "scene_id", "title", "created_at", "updated_at"])
    data["title"] = data.get("title") or "New Chat"
    data["message_count"] = message_count
    return data
