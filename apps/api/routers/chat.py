"""Chat endpoint with SSE streaming — multi-agent orchestrator architecture.

Upgraded from monolithic single-handler to Orchestrator + Specialist Agent pattern.
Borrows from: MetaGPT Team, HelloAgents ProgrammingTutor, OpenClaw multi-agent config.

The orchestrator handles:
1. Intent classification (rule pre-match + LLM fallback)
2. Parallel context loading (preferences, memories, RAG)
3. Routing to specialist agent (TeachingAgent, ExerciseAgent, etc.)
4. SSE streaming with [ACTION:...] marker parsing
5. Async post-processing (signal extraction, memory encoding)
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from database import get_db, async_session
from models.chat_message import ChatMessageLog
from models.chat_session import ChatSession
from models.user import User
from schemas.chat import ChatRequest
from services.agent.orchestrator import orchestrate_stream
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_session_title(message: str) -> str:
    normalized = " ".join(message.strip().split())
    if not normalized:
        return "New Chat"
    return normalized[:77] + "..." if len(normalized) > 80 else normalized


async def _resolve_chat_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    scene_id: str | None,
    message: str,
    session_id: uuid.UUID | None,
) -> ChatSession:
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
            raise HTTPException(status_code=404, detail="Chat session not found")
        if scene_id and session.scene_id != scene_id:
            session.scene_id = scene_id
        if not session.title:
            session.title = _build_session_title(message)
        await db.flush()
        return session

    session = ChatSession(
        user_id=user_id,
        course_id=course_id,
        scene_id=scene_id,
        title=_build_session_title(message),
    )
    db.add(session)
    await db.flush()
    return session


async def _persist_chat_turn(
    db: AsyncSession,
    session: ChatSession,
    user_message: str,
    assistant_message: str,
) -> None:
    if not assistant_message.strip():
        return
    db.add_all(
        [
            ChatMessageLog(session_id=session.id, role="user", content=user_message),
            ChatMessageLog(session_id=session.id, role="assistant", content=assistant_message),
        ]
    )
    session.updated_at = datetime.now(timezone.utc)
    await db.commit()


def _serialize_session(session: ChatSession, message_count: int) -> dict:
    return {
        "id": str(session.id),
        "course_id": str(session.course_id),
        "scene_id": session.scene_id,
        "title": session.title or "New Chat",
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "message_count": message_count,
    }


@router.get("/courses/{course_id}/sessions")
async def list_chat_sessions(
    course_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count_subquery = (
        select(
            ChatMessageLog.session_id,
            func.count(ChatMessageLog.id).label("message_count"),
        )
        .group_by(ChatMessageLog.session_id)
        .subquery()
    )
    result = await db.execute(
        select(ChatSession, func.coalesce(count_subquery.c.message_count, 0))
        .outerjoin(count_subquery, ChatSession.id == count_subquery.c.session_id)
        .where(
            ChatSession.user_id == user.id,
            ChatSession.course_id == course_id,
        )
        .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_serialize_session(session, message_count) for session, message_count in result.all()]


@router.get("/sessions/{session_id}/messages")
async def get_chat_session_messages(
    session_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session_result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        )
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    result = await db.execute(
        select(ChatMessageLog)
        .where(ChatMessageLog.session_id == session_id)
        .order_by(ChatMessageLog.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    messages = result.scalars().all()
    return {
        "session": _serialize_session(session, len(messages)),
        "messages": [
            {
                "id": str(message.id),
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }
            for message in messages
        ],
    }


@router.post("/")
async def chat_stream(body: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Stream chat response using multi-agent orchestrator via SSE."""
    course = await get_course_or_404(db, body.course_id, user_id=user.id)

    resolved_scene = body.scene or course.active_scene
    session = await _resolve_chat_session(
        db=db,
        user_id=user.id,
        course_id=body.course_id,
        scene_id=resolved_scene,
        message=body.message,
        session_id=body.session_id,
    )
    await db.commit()

    async def event_generator():
        assistant_chunks: list[str] = []
        assistant_content = ""
        try:
            async for event in orchestrate_stream(
                user_id=user.id,
                course_id=body.course_id,
                message=body.message,
                db=db,
                db_factory=async_session,
                conversation_id=body.conversation_id,
                session_id=session.id,
                history=[m.model_dump() for m in body.history],
                active_tab=body.active_tab or "",
                tab_context=body.tab_context,
                scene=resolved_scene,
            ):
                if event.get("event") == "message":
                    try:
                        payload = json.loads(event["data"])
                    except (KeyError, json.JSONDecodeError, TypeError):
                        payload = {}
                    if payload.get("content"):
                        assistant_chunks.append(payload["content"])
                        assistant_content = "".join(assistant_chunks)
                elif event.get("event") == "replace":
                    try:
                        payload = json.loads(event["data"])
                    except (KeyError, json.JSONDecodeError, TypeError):
                        payload = {}
                    assistant_content = payload.get("content", assistant_content)
                yield event
            await _persist_chat_turn(db, session, body.message, assistant_content)
        except Exception as e:
            logger.error("Orchestrator error: %s", e, exc_info=True)
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(event_generator())
