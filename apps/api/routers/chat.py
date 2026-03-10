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

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from database import get_db, async_session
from sqlalchemy.exc import SQLAlchemyError

from libs.exceptions import AppError, NotFoundError, reraise_as_app_error
from models.chat_message import ChatMessageLog
from models.chat_session import ChatSession
from models.user import User
from schemas.chat import ChatRequest
from services.agent.orchestrator import orchestrate_stream
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.llm.readiness import ensure_llm_ready
from utils.serializers import serialize_model

# Helpers extracted to chat_helpers — re-export for backward compatibility
from .chat_helpers import (
    build_session_title as _build_session_title,
    resolve_chat_session as _resolve_chat_session,
    persist_chat_turn as _persist_chat_turn,
    serialize_session as _serialize_session,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/courses/{course_id}/sessions", summary="List chat sessions", description="Return paginated chat sessions for a course, ordered by most recent activity.")
async def list_chat_sessions(
    course_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
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


@router.get("/sessions/{session_id}/messages", summary="Get session messages", description="Return paginated messages for a chat session with session metadata.")
async def get_chat_session_messages(
    session_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
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
        raise NotFoundError("Chat session", session_id)

    count_result = await db.execute(
        select(func.count(ChatMessageLog.id)).where(ChatMessageLog.session_id == session_id)
    )
    total_count = count_result.scalar() or 0

    result = await db.execute(
        select(ChatMessageLog)
        .where(ChatMessageLog.session_id == session_id)
        .order_by(ChatMessageLog.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    messages = result.scalars().all()
    return {
        "session": _serialize_session(session, total_count),
        "messages": [
            serialize_model(message, ["id", "role", "content", "metadata_json", "created_at"])
            for message in messages
        ],
    }


@router.post("/", summary="Send chat message", description="Stream a tutoring response via SSE using the multi-agent orchestrator.")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream chat response using multi-agent orchestrator via SSE."""
    from middleware.security import detect_prompt_injection, sanitize_user_input

    body.message = sanitize_user_input(body.message)
    client_ip = request.client.host if request.client else "unknown"
    if detect_prompt_injection(body.message, client_ip=client_ip):
        logger.warning("Prompt injection detected from user %s: %.100s", user.id, body.message)

        async def injection_error():
            yield {
                "event": "error",
                "data": json.dumps({"error": "Your message was flagged by our safety filter. Please rephrase your request."}),
            }

        return EventSourceResponse(injection_error())

    # v3.2: User interrupt/steering — give the agent context that the user
    # interrupted a previous response to redirect the conversation.
    if body.interrupt:
        body.message = f"[User interrupted the previous response to say:] {body.message}"

    course = await get_course_or_404(db, body.course_id, user_id=user.id)
    await ensure_llm_ready("Chat tutoring")
    session_factory = getattr(request.app.state, "test_session_factory", None) or async_session

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

    # SSE stream timeout: 5 minutes max to prevent resource exhaustion from dangling connections
    _SSE_TIMEOUT_SECONDS = 300

    async def event_generator():
        import asyncio

        assistant_chunks: list[str] = []
        assistant_content = ""
        assistant_metadata: dict | None = None
        try:
            async with asyncio.timeout(_SSE_TIMEOUT_SECONDS):
                async for event in orchestrate_stream(
                    user_id=user.id,
                    course_id=body.course_id,
                    message=body.message,
                    db=db,
                    db_factory=session_factory,
                    conversation_id=body.conversation_id,
                    session_id=session.id,
                    history=[m.model_dump() for m in body.history],
                    active_tab=body.active_tab or "",
                    tab_context=body.tab_context,
                    scene=resolved_scene,
                    images=[img.model_dump() for img in body.images] if body.images else None,
                    learning_mode=body.learning_mode,
                    block_types=body.block_types or None,
                    dismissed_block_types=body.dismissed_block_types or None,
                ):
                    # Stop streaming if client disconnected (saves LLM cost)
                    if await request.is_disconnected():
                        logger.info("Client disconnected during SSE stream for session %s", session.id)
                        break
                    if event.get("event") == "message":
                        try:
                            payload = json.loads(event["data"])
                        except (KeyError, json.JSONDecodeError, TypeError):
                            payload = {}
                        if payload.get("content"):
                            assistant_chunks.append(payload["content"])
                            assistant_content = "".join(assistant_chunks)
                    elif event.get("event") == "done":
                        try:
                            payload = json.loads(event["data"])
                        except (KeyError, json.JSONDecodeError, TypeError):
                            payload = {}
                        assistant_metadata = {
                            "agent": payload.get("agent"),
                            "intent": payload.get("intent"),
                            "tokens": payload.get("tokens"),
                            "provenance": payload.get("provenance"),
                            "actions": payload.get("actions", []),
                            "verifier": payload.get("verifier"),
                            "verifier_diagnostics": payload.get("verifier_diagnostics"),
                            "task_link": payload.get("task_link"),
                            "reflection": payload.get("reflection"),
                        }
                    elif event.get("event") == "replace":
                        try:
                            payload = json.loads(event["data"])
                        except (KeyError, json.JSONDecodeError, TypeError):
                            payload = {}
                        assistant_content = payload.get("content", assistant_content)
                    yield event
            # Use a fresh DB session for persistence to avoid stale state after SSE streaming
            try:
                async with session_factory() as persist_db:
                    await _persist_chat_turn(persist_db, session.id, body.message, assistant_content, assistant_metadata)
            except SQLAlchemyError as persist_err:
                logger.exception("Failed to persist chat turn: %s", persist_err)
        except TimeoutError:
            logger.warning("SSE stream timed out after %ds for session %s", _SSE_TIMEOUT_SECONDS, session.id)
            yield {"event": "error", "data": json.dumps({"error": "Response timed out. Please try again with a simpler question."})}
        except AppError as e:
            logger.exception("Orchestrator AppError: %s", e)
            yield {"event": "error", "data": json.dumps({"error": e.message})}
        except (ValueError, KeyError, SQLAlchemyError, ConnectionError, OSError, RuntimeError) as e:
            from libs.exceptions import is_llm_unavailable_error
            if is_llm_unavailable_error(e):
                error_msg = "The AI service is temporarily unavailable. Please try again shortly."
            else:
                error_msg = "An internal error occurred. Please try again."
            logger.exception("Orchestrator error: %s", e)
            yield {"event": "error", "data": json.dumps({"error": error_msg})}

    return EventSourceResponse(event_generator())


@router.get("/greeting/{course_id}", summary="Get personalized greeting", description="Generate a context-aware greeting using mastery graph and review state.")
async def get_greeting(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a personalized AI greeting when entering a course.

    Uses LOOM mastery graph and LECTOR review state to craft a context-aware
    greeting that tells the student what to focus on.
    """
    from models.course import Course

    course = await get_course_or_404(db, course_id, user_id=user.id)

    # Gather learning state
    greeting_parts = [f"Welcome back to **{course.name}**!"]

    try:
        from services.lector import get_review_summary
        review = await get_review_summary(db, user.id, course_id)

        if review["needs_review"] and review["urgent_count"] > 0:
            concepts = review["concepts_at_risk"][:3]
            if concepts:
                concept_list = ", ".join(f"**{c}**" for c in concepts)
                greeting_parts.append(
                    f"You have {review['urgent_count']} concept(s) that could use a review: {concept_list}."
                )
            greeting_parts.append("Want me to start a quick review session?")
        else:
            greeting_parts.append("You're all caught up on reviews!")
    except (SQLAlchemyError, ValueError, KeyError, TypeError) as exc:
        logger.exception("Failed to fetch review summary for greeting")

    try:
        from services.loom import get_mastery_graph
        graph = await get_mastery_graph(db, user.id, course_id)

        if graph.get("weak_concepts"):
            weak = [c["name"] for c in graph["weak_concepts"][:2]]
            greeting_parts.append(
                f"Areas to strengthen: {', '.join(weak)}."
            )
        elif graph.get("nodes"):
            mastered = sum(1 for n in graph["nodes"] if n.get("mastery", 0) >= 0.8)
            total = len(graph["nodes"])
            if total > 0:
                greeting_parts.append(
                    f"You've mastered {mastered}/{total} concepts so far."
                )
    except (SQLAlchemyError, ValueError, KeyError, TypeError) as exc:
        logger.exception("Failed to fetch mastery graph for greeting")

    # Check for upcoming deadlines
    try:
        from models.ingestion import Assignment
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(Assignment)
            .where(
                Assignment.course_id == course_id,
                Assignment.user_id == user.id,
                Assignment.due_date >= now,
            )
            .order_by(Assignment.due_date.asc())
            .limit(1)
        )
        upcoming = result.scalar_one_or_none()
        if upcoming:
            days_until = (upcoming.due_date - now).days
            if days_until <= 3:
                greeting_parts.append(
                    f"Heads up: **{upcoming.title}** is due in {days_until} day(s)!"
                )
    except (SQLAlchemyError, ValueError, TypeError) as exc:
        logger.exception("Failed to fetch upcoming deadlines for greeting")

    greeting_parts.append("What would you like to work on?")

    # Build suggested actions based on greeting context
    suggested_actions: list[dict[str, str]] = []
    try:
        if review.get("needs_review") and review.get("urgent_count", 0) > 0:
            suggested_actions.append({
                "action": "agent_insight",
                "value": "review_needed",
                "extra": f"{review['urgent_count']} concept(s) at risk",
            })
    except NameError:
        logger.debug("review variable not available for suggested actions")
    try:
        if upcoming and days_until <= 7:
            suggested_actions.append({
                "action": "suggest_mode",
                "value": "exam_prep",
                "extra": f"{upcoming.title} due in {days_until} day(s)",
            })
    except NameError:
        logger.debug("upcoming variable not available for suggested actions")

    return {
        "greeting": " ".join(greeting_parts),
        "course_name": course.name,
        "suggested_actions": suggested_actions,
    }
