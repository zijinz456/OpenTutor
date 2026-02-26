"""Chat endpoint with SSE streaming, course content RAG, and async signal extraction."""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from database import get_db
from models.course import Course
from models.preference import PreferenceSignal
from schemas.chat import ChatRequest
from services.llm.router import get_llm_client
from services.preference.engine import resolve_preferences
from services.preference.extractor import extract_preference_signal
from services.preference.confidence import process_signal_to_preference
from services.memory.pipeline import encode_memory, retrieve_memories
from services.auth.dependency import get_current_user
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


async def search_content_tree(db: AsyncSession, course_id: uuid.UUID, query: str) -> list[dict]:
    """Hybrid search over content tree using RRF fusion ranking.

    Phase 1: combines keyword + tree + vector search via RRF.
    """
    from services.search.hybrid import hybrid_search

    return await hybrid_search(db, course_id, query, limit=5)


"""
NL Tool Definitions (CopilotKit pattern).

When the user requests a layout change or preference update, the LLM
outputs an [ACTION:...] marker which the frontend intercepts and executes.
This avoids needing provider-specific function calling — works with any LLM.
"""

NL_TOOLS_PROMPT = """
## Available Actions

You can control the learning interface by outputting action markers.
Use these ONLY when the user explicitly asks to change layout or preferences.
Output the marker on its own line, then continue your normal response.

Layout presets (set_layout_preset):
- balanced: Equal panel sizes
- notesFocused: Expand notes panel
- quizFocused: Expand quiz panel
- chatFocused: Expand chat panel
- fullNotes: Maximize notes panel

Format: [ACTION:set_layout_preset:<preset_name>]
Example: User says "放大笔记" → [ACTION:set_layout_preset:notesFocused]

Preference updates (set_preference):
- note_format: bullet_point | table | mind_map | step_by_step | summary
- detail_level: concise | balanced | detailed
- language: en | zh | auto
- explanation_style: formal | conversational | socratic | example_heavy

Format: [ACTION:set_preference:<dimension>:<value>]
Example: User says "太长了" → [ACTION:set_preference:detail_level:concise]
Example: User says "换成表格" → [ACTION:set_preference:note_format:table]

Rules:
- Only output ONE action per response
- Always explain what you changed after the action marker
- If the request is ambiguous, ask for clarification instead of guessing
"""


def build_system_prompt(
    preferences: dict[str, str],
    context_docs: list[dict],
    memories: list[dict] | None = None,
) -> str:
    """Build system prompt with preference injection, RAG context, memories, and NL tools."""
    parts = [
        "You are OpenTutor, a personalized learning assistant.",
        "Answer based on the course materials provided below.",
        "If the answer is not in the materials, say so clearly.",
    ]

    # NL layout/preference tools (CopilotKit pattern)
    parts.append(NL_TOOLS_PROMPT)

    # Preference injection
    if preferences:
        pref_lines = [f"- {k}: {v}" for k, v in preferences.items()]
        parts.append(f"\nUser preferences:\n" + "\n".join(pref_lines))

    # Memory context (EverMemOS retrieve stage)
    if memories:
        parts.append("\n## Previous Interactions (memory):\n")
        for mem in memories:
            parts.append(f"- {mem['summary']}")

    # RAG context
    if context_docs:
        parts.append("\n## Course Materials (retrieved sections):\n")
        for doc in context_docs:
            parts.append(f"### {doc['title']}\n{doc['content']}\n")

    return "\n".join(parts)


@router.post("/")
async def chat_stream(body: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Stream chat response using SSE."""
    # Verify course exists
    result = await db.execute(select(Course).where(Course.id == body.course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    # Detect scene for preference cascade
    from services.preference.scene import detect_scene

    scene = detect_scene(body.message, course.name if course else None)

    # Resolve preferences (7-layer cascade with scene)
    resolved = await resolve_preferences(db, user.id, body.course_id, scene=scene)

    # Search content tree for RAG
    context_docs = await search_content_tree(db, body.course_id, body.message)

    # Retrieve relevant memories (EverMemOS Stage 3)
    memories = await retrieve_memories(db, user.id, body.message, body.course_id, limit=3)

    # Build system prompt
    system_prompt = build_system_prompt(resolved.preferences, context_docs, memories)

    # Get LLM client and stream
    client = get_llm_client()

    async def event_generator():
        full_response = ""
        try:
            buffer = ""
            async for chunk in client.stream_chat(system_prompt, body.message):
                buffer += chunk
                # Check for [ACTION:...] markers in the accumulated buffer
                while "[ACTION:" in buffer:
                    start = buffer.index("[ACTION:")
                    end = buffer.find("]", start)
                    if end == -1:
                        break
                    before = buffer[:start]
                    if before:
                        full_response += before
                        yield {"event": "message", "data": json.dumps({"content": before})}
                    marker = buffer[start + 8 : end]
                    parts = marker.split(":")
                    action_data = {"action": parts[0]}
                    if len(parts) >= 2:
                        action_data["value"] = parts[1]
                    if len(parts) >= 3:
                        action_data["extra"] = parts[2]
                    yield {"event": "action", "data": json.dumps(action_data)}
                    buffer = buffer[end + 1 :]
                if buffer and "[ACTION:" not in buffer:
                    full_response += buffer
                    yield {"event": "message", "data": json.dumps({"content": buffer})}
                    buffer = ""
            if buffer:
                full_response += buffer
                yield {"event": "message", "data": json.dumps({"content": buffer})}
            yield {"event": "done", "data": json.dumps({"status": "complete"})}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

        # Phase 0-C: Async post-processing (openakita Compiler pattern)
        # Fire-and-forget after stream completes
        if full_response:
            # 1. Preference signal extraction (~95% return NONE)
            asyncio.create_task(
                _extract_and_store_signal(
                    body.message, full_response, user.id, body.course_id
                )
            )
            # 2. Memory encoding (EverMemOS Stage 1)
            asyncio.create_task(
                _encode_memory(
                    body.message, full_response, user.id, body.course_id
                )
            )

    return EventSourceResponse(event_generator())


async def _extract_and_store_signal(
    user_message: str,
    assistant_response: str,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> None:
    """Extract preference signal from conversation and store if found.

    Runs asynchronously after the chat stream completes (Compiler pattern).
    """
    try:
        signal = await extract_preference_signal(
            user_message, assistant_response, user_id, course_id
        )
        if not signal:
            return

        # Store signal in DB
        from database import async_session

        async with async_session() as db:
            ps = PreferenceSignal(
                user_id=signal["user_id"],
                course_id=signal.get("course_id"),
                signal_type=signal["signal_type"],
                dimension=signal["dimension"],
                value=signal["value"],
                context=signal.get("context"),
            )
            db.add(ps)
            await db.commit()

            # Check if enough signals to promote to preference
            await process_signal_to_preference(
                db, signal["user_id"], signal["dimension"], signal.get("course_id")
            )
            await db.commit()

        logger.info(
            "Preference signal extracted: user_id=%s course_id=%s dimension=%s value=%s",
            signal["user_id"],
            signal.get("course_id"),
            signal["dimension"],
            signal["value"],
        )
    except Exception as e:
        logger.warning("Signal extraction/storage failed: %s", e, exc_info=True)


async def _encode_memory(
    user_message: str,
    assistant_response: str,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> None:
    """Encode conversation turn into memory (EverMemOS Stage 1)."""
    try:
        from database import async_session

        async with async_session() as db:
            await encode_memory(db, user_id, course_id, user_message, assistant_response)
            await db.commit()
    except Exception as e:
        logger.warning(
            "Memory encoding failed: user_id=%s course_id=%s error=%s",
            user_id,
            course_id,
            e,
            exc_info=True,
        )
