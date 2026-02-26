"""Chat endpoint with SSE streaming and course content RAG."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from database import get_db
from models.course import Course
from models.content import CourseContentTree
from schemas.chat import ChatRequest
from services.llm.router import get_llm_client
from services.preference.engine import resolve_preferences
from routers.courses import get_or_create_user

router = APIRouter()


async def search_content_tree(db: AsyncSession, course_id: uuid.UUID, query: str) -> list[dict]:
    """Simple keyword search over content tree nodes for RAG context.

    Phase 0: basic LIKE search. Phase 1: PageIndex tree reasoning search.
    """
    result = await db.execute(
        select(CourseContentTree)
        .where(
            CourseContentTree.course_id == course_id,
            CourseContentTree.content.ilike(f"%{query[:100]}%"),
        )
        .limit(5)
    )
    nodes = result.scalars().all()
    return [
        {"title": n.title, "content": (n.content or "")[:1000], "level": n.level}
        for n in nodes
    ]


def build_system_prompt(preferences: dict[str, str], context_docs: list[dict]) -> str:
    """Build system prompt with preference injection and RAG context."""
    parts = [
        "You are OpenTutor, a personalized learning assistant.",
        "Answer based on the course materials provided below.",
        "If the answer is not in the materials, say so clearly.",
    ]

    # Preference injection
    if preferences:
        pref_lines = [f"- {k}: {v}" for k, v in preferences.items()]
        parts.append(f"\nUser preferences:\n" + "\n".join(pref_lines))

    # RAG context
    if context_docs:
        parts.append("\n## Course Materials (retrieved sections):\n")
        for doc in context_docs:
            parts.append(f"### {doc['title']}\n{doc['content']}\n")

    return "\n".join(parts)


@router.post("/")
async def chat_stream(body: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Stream chat response using SSE."""
    # Verify course exists
    result = await db.execute(select(Course).where(Course.id == body.course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    user = await get_or_create_user(db)

    # Resolve preferences
    resolved = await resolve_preferences(db, user.id, body.course_id)

    # Search content tree for RAG
    context_docs = await search_content_tree(db, body.course_id, body.message)

    # Build system prompt
    system_prompt = build_system_prompt(resolved.preferences, context_docs)

    # Get LLM client and stream
    client = get_llm_client()

    async def event_generator():
        try:
            async for chunk in client.stream_chat(system_prompt, body.message):
                yield {"event": "message", "data": json.dumps({"content": chunk})}
            yield {"event": "done", "data": json.dumps({"status": "complete"})}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(event_generator())
