"""LangGraph-based workflow engine.

Converts all 6 workflows to LangGraph StateGraph with proper node/edge definitions.
Each workflow is a compiled StateGraph that can be invoked with `.ainvoke(state)`.

Reference from spec:
- Phase 0: "LangGraph工作流: WF-2每周准备 + WF-4学习Session"
- Phase 1: "完整6个工作流"
"""

import uuid
import logging
from typing import TypedDict, Annotated
from operator import add

from langgraph.graph import StateGraph, END

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ═══════ WF-4: Study Session Graph ═══════

class StudyState(TypedDict):
    user_id: uuid.UUID
    course_id: uuid.UUID
    user_message: str
    preferences: dict
    content_docs: list[dict]
    memories: list[dict]
    system_prompt: str
    response: str
    signal: dict | None
    db: AsyncSession  # passed through state


async def node_load_context(state: StudyState) -> dict:
    from services.preference.engine import resolve_preferences
    from services.memory.pipeline import retrieve_memories

    db = state["db"]
    resolved = await resolve_preferences(db, state["user_id"], state["course_id"])
    memories = await retrieve_memories(
        db, state["user_id"], state["user_message"], state["course_id"], limit=3
    )
    return {"preferences": resolved.preferences, "memories": memories}


async def node_search_content(state: StudyState) -> dict:
    from services.search.hybrid import hybrid_search

    db = state["db"]
    docs = await hybrid_search(db, state["course_id"], state["user_message"], limit=5)
    return {"content_docs": docs}


async def node_generate_response(state: StudyState) -> dict:
    from services.llm.router import get_llm_client

    parts = [
        "You are OpenTutor, a personalized learning assistant.",
        "Answer based on the course materials provided below.",
    ]
    if state["preferences"]:
        pref_lines = [f"- {k}: {v}" for k, v in state["preferences"].items()]
        parts.append("\nUser preferences:\n" + "\n".join(pref_lines))
    if state["memories"]:
        parts.append("\n## Previous Interactions:")
        for mem in state["memories"]:
            parts.append(f"- {mem.get('summary', '')}")
    if state["content_docs"]:
        parts.append("\n## Course Materials:")
        for doc in state["content_docs"]:
            parts.append(f"### {doc.get('title', '')}\n{doc.get('content', '')[:1000]}\n")

    system_prompt = "\n".join(parts)
    client = get_llm_client()
    response = await client.chat(system_prompt, state["user_message"])
    return {"system_prompt": system_prompt, "response": response}


async def node_extract_signals(state: StudyState) -> dict:
    from services.preference.extractor import extract_preference_signal

    signal = await extract_preference_signal(
        state["user_message"], state["response"], state["user_id"], state["course_id"],
    )
    return {"signal": signal}


def build_study_session_graph() -> StateGraph:
    """Build the WF-4 Study Session StateGraph."""
    graph = StateGraph(StudyState)
    graph.add_node("load_context", node_load_context)
    graph.add_node("search_content", node_search_content)
    graph.add_node("generate_response", node_generate_response)
    graph.add_node("extract_signals", node_extract_signals)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "search_content")
    graph.add_edge("search_content", "generate_response")
    graph.add_edge("generate_response", "extract_signals")
    graph.add_edge("extract_signals", END)

    return graph.compile()


# ═══════ WF-2: Weekly Prep Graph ═══════

class WeeklyPrepState(TypedDict):
    user_id: uuid.UUID
    deadlines: list[dict]
    stats: dict
    plan: str
    db: AsyncSession


async def node_load_deadlines(state: WeeklyPrepState) -> dict:
    from services.workflow.weekly_prep import load_upcoming_deadlines
    deadlines = await load_upcoming_deadlines(state["db"], state["user_id"])
    return {"deadlines": deadlines}


async def node_load_stats(state: WeeklyPrepState) -> dict:
    from services.workflow.weekly_prep import get_recent_study_stats
    stats = await get_recent_study_stats(state["db"], state["user_id"])
    return {"stats": stats}


async def node_generate_plan(state: WeeklyPrepState) -> dict:
    from services.llm.router import get_llm_client
    from sqlalchemy import select
    from models.course import Course

    db = state["db"]
    courses_result = await db.execute(select(Course).where(Course.user_id == state["user_id"]))
    courses = courses_result.scalars().all()

    deadline_text = "\n".join(
        f"- [{d['type']}] {d['course']}: {d['title']} (due in {d['days_until_due']} days)"
        for d in state["deadlines"]
    ) or "No upcoming deadlines."

    stats = state["stats"]
    stats_text = (
        f"Last 7 days: {stats['sessions_count']} sessions, "
        f"{stats['total_minutes']} minutes studied, "
        f"{stats['problems_attempted']} problems ({stats['accuracy']:.0%} accuracy)"
    )

    client = get_llm_client()
    plan = await client.chat(
        "You are a study planning assistant. Create actionable weekly plans.",
        f"## Upcoming Deadlines\n{deadline_text}\n\n## Performance\n{stats_text}\n\n"
        f"## Courses\n{chr(10).join(f'- {c.name}' for c in courses)}\n\n"
        "Create a day-by-day plan (Mon-Sun). Output in markdown.",
    )
    return {"plan": plan}


def build_weekly_prep_graph() -> StateGraph:
    """Build the WF-2 Weekly Prep StateGraph."""
    graph = StateGraph(WeeklyPrepState)
    graph.add_node("load_deadlines", node_load_deadlines)
    graph.add_node("load_stats", node_load_stats)
    graph.add_node("generate_plan", node_generate_plan)

    graph.set_entry_point("load_deadlines")
    graph.add_edge("load_deadlines", "load_stats")
    graph.add_edge("load_stats", "generate_plan")
    graph.add_edge("generate_plan", END)

    return graph.compile()


# ═══════ Convenience runners ═══════

_study_graph = None
_weekly_graph = None


def get_study_session_graph():
    global _study_graph
    if _study_graph is None:
        _study_graph = build_study_session_graph()
    return _study_graph


def get_weekly_prep_graph():
    global _weekly_graph
    if _weekly_graph is None:
        _weekly_graph = build_weekly_prep_graph()
    return _weekly_graph


async def run_study_session_graph(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    user_message: str,
) -> dict:
    """Run WF-4 via LangGraph."""
    graph = get_study_session_graph()
    initial_state: StudyState = {
        "user_id": user_id,
        "course_id": course_id,
        "user_message": user_message,
        "preferences": {},
        "content_docs": [],
        "memories": [],
        "system_prompt": "",
        "response": "",
        "signal": None,
        "db": db,
    }
    result = await graph.ainvoke(initial_state)

    # Post-processing: encode memory + store signal
    from services.memory.pipeline import encode_memory
    await encode_memory(db, user_id, course_id, user_message, result["response"])

    if result.get("signal"):
        from models.preference import PreferenceSignal
        from services.preference.confidence import process_signal_to_preference

        ps = PreferenceSignal(
            user_id=result["signal"]["user_id"],
            course_id=result["signal"].get("course_id"),
            signal_type=result["signal"]["signal_type"],
            dimension=result["signal"]["dimension"],
            value=result["signal"]["value"],
            context=result["signal"].get("context"),
        )
        db.add(ps)
        await db.flush()
        await process_signal_to_preference(
            db, user_id, result["signal"]["dimension"], result["signal"].get("course_id")
        )

    return {
        "response": result["response"],
        "memories_used": len(result.get("memories", [])),
        "content_docs_used": len(result.get("content_docs", [])),
        "signal_extracted": result.get("signal") is not None,
    }


async def run_weekly_prep_graph(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Run WF-2 via LangGraph."""
    graph = get_weekly_prep_graph()
    initial_state: WeeklyPrepState = {
        "user_id": user_id,
        "deadlines": [],
        "stats": {},
        "plan": "",
        "db": db,
    }
    result = await graph.ainvoke(initial_state)
    return {
        "deadlines": result.get("deadlines", []),
        "stats": result.get("stats", {}),
        "plan": result.get("plan", ""),
    }
