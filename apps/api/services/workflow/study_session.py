"""WF-4: Study Session Workflow — LangGraph implementation.

Flow: load_context → search_content → generate_response → extract_signals

Reference from spec:
- WF-4 is the core learning loop workflow
- Each node is a LangGraph StateGraph node
- Preference signals are extracted asynchronously after response generation

Phase 0-C: Simple sequential pipeline using LangGraph StateGraph.
Phase 1: Add branching (quiz mode, review mode, explore mode).
"""

import uuid
import logging
from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from services.llm.router import get_llm_client
from services.preference.engine import resolve_preferences
from services.memory.pipeline import retrieve_memories, encode_memory
from services.preference.extractor import extract_preference_signal

logger = logging.getLogger(__name__)


class StudySessionState(TypedDict):
    """State that flows through the WF-4 study session workflow."""

    # Input
    user_id: uuid.UUID
    course_id: uuid.UUID
    user_message: str

    # Accumulated context
    preferences: dict[str, str]
    content_docs: list[dict]
    memories: list[dict]
    system_prompt: str

    # Output
    response: str
    signal: dict | None


async def load_context(
    state: StudySessionState,
    db: AsyncSession,
) -> StudySessionState:
    """Node 1: Load user preferences and conversation memories."""
    resolved = await resolve_preferences(db, state["user_id"], state["course_id"])
    state["preferences"] = resolved.preferences

    memories = await retrieve_memories(
        db, state["user_id"], state["user_message"], state["course_id"], limit=3
    )
    state["memories"] = memories

    return state


async def search_content(
    state: StudySessionState,
    db: AsyncSession,
) -> StudySessionState:
    """Node 2: Search course content tree for relevant RAG context."""
    from sqlalchemy import select
    from models.content import CourseContentTree

    query = state["user_message"][:100]
    result = await db.execute(
        select(CourseContentTree)
        .where(
            CourseContentTree.course_id == state["course_id"],
            CourseContentTree.content.ilike(f"%{query}%"),
        )
        .limit(5)
    )
    nodes = result.scalars().all()
    state["content_docs"] = [
        {"title": n.title, "content": (n.content or "")[:1000], "level": n.level}
        for n in nodes
    ]

    return state


async def generate_response(state: StudySessionState) -> StudySessionState:
    """Node 3: Generate LLM response with full context."""
    parts = [
        "You are OpenTutor, a personalized learning assistant.",
        "Answer based on the course materials provided below.",
    ]

    if state["preferences"]:
        pref_lines = [f"- {k}: {v}" for k, v in state["preferences"].items()]
        parts.append("\nUser preferences:\n" + "\n".join(pref_lines))

    if state["memories"]:
        parts.append("\n## Previous Interactions:\n")
        for mem in state["memories"]:
            parts.append(f"- {mem['summary']}")

    if state["content_docs"]:
        parts.append("\n## Course Materials:\n")
        for doc in state["content_docs"]:
            parts.append(f"### {doc['title']}\n{doc['content']}\n")

    system_prompt = "\n".join(parts)
    state["system_prompt"] = system_prompt

    client = get_llm_client()
    state["response"] = await client.chat(system_prompt, state["user_message"])

    return state


async def extract_signals(state: StudySessionState) -> StudySessionState:
    """Node 4: Extract preference signals from the conversation."""
    signal = await extract_preference_signal(
        state["user_message"],
        state["response"],
        state["user_id"],
        state["course_id"],
    )
    state["signal"] = signal
    return state


async def run_study_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    user_message: str,
) -> dict:
    """Execute the WF-4 study session workflow.

    Sequential pipeline: load_context → search_content → generate_response → extract_signals

    Phase 0-C: Simple sequential execution.
    Phase 1: LangGraph StateGraph with conditional branching.
    """
    state: StudySessionState = {
        "user_id": user_id,
        "course_id": course_id,
        "user_message": user_message,
        "preferences": {},
        "content_docs": [],
        "memories": [],
        "system_prompt": "",
        "response": "",
        "signal": None,
    }

    # Execute pipeline
    state = await load_context(state, db)
    state = await search_content(state, db)
    state = await generate_response(state)
    state = await extract_signals(state)

    # Encode memory (EverMemOS Stage 1)
    await encode_memory(db, user_id, course_id, user_message, state["response"])

    # Store preference signal if found
    if state["signal"]:
        from models.preference import PreferenceSignal
        from services.preference.confidence import process_signal_to_preference

        ps = PreferenceSignal(
            user_id=state["signal"]["user_id"],
            course_id=state["signal"].get("course_id"),
            signal_type=state["signal"]["signal_type"],
            dimension=state["signal"]["dimension"],
            value=state["signal"]["value"],
            context=state["signal"].get("context"),
        )
        db.add(ps)
        await db.flush()
        await process_signal_to_preference(
            db, user_id, state["signal"]["dimension"], state["signal"].get("course_id")
        )

    return {
        "response": state["response"],
        "memories_used": len(state["memories"]),
        "content_docs_used": len(state["content_docs"]),
        "signal_extracted": state["signal"] is not None,
    }
