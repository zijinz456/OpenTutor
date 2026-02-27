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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from database import get_db, async_session
from models.course import Course
from schemas.chat import ChatRequest
from services.agent.orchestrator import orchestrate_stream
from services.auth.dependency import get_current_user
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/")
async def chat_stream(body: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Stream chat response using multi-agent orchestrator via SSE."""
    # Verify course exists
    result = await db.execute(select(Course).where(Course.id == body.course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    async def event_generator():
        try:
            async for event in orchestrate_stream(
                user_id=user.id,
                course_id=body.course_id,
                message=body.message,
                db=db,
                db_factory=async_session,
                conversation_id=body.conversation_id,
                history=[m.model_dump() for m in body.history],
                active_tab=body.active_tab or "",
                tab_context=body.tab_context,
                scene=body.scene or course.active_scene,
            ):
                yield event
        except Exception as e:
            logger.error("Orchestrator error: %s", e, exc_info=True)
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(event_generator())
