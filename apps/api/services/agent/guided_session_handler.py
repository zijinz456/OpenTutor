"""Guided session handler — routes [GUIDED_SESSION:...] messages to specialist agents.

Extracted from orchestrator.py. Handles session start/resume/pause actions
and streams phase-specific agent responses.
"""

import json
import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext, IntentType
from services.agent.registry import get_agent
from services.agent.context_builder import load_context
from services.agent.marker_parser import MarkerParser

logger = logging.getLogger(__name__)

_PHASE_TO_INTENT = {
    "warmup": IntentType.LEARN,    # ReviewAgent handles review
    "teach": IntentType.LEARN,     # TeachingAgent
    "practice": IntentType.LEARN,  # ExerciseAgent
    "summary": IntentType.LEARN,   # TeachingAgent
}


async def handle_guided_session(
    ctx: AgentContext,
    db: AsyncSession,
    action: str,
    task_id: str,
) -> AsyncIterator[dict]:
    """Handle [GUIDED_SESSION:action:task_id] messages.

    Routes to existing specialist agents with phase-specific prompts.
    """
    from services.agent.guided_session import (
        get_session_state, advance_phase, pause_session, resume_session,
        build_phase_prompt,
    )

    if action == "pause":
        state = await pause_session(db, ctx.user_id, task_id)
        yield {"event": "message", "data": json.dumps({"content": "Session paused. You can resume anytime."})}
        yield {"event": "action", "data": json.dumps({"type": "guided_session_paused", "task_id": task_id})}
        yield {"event": "done", "data": json.dumps({"guided_session": "paused"})}
        return

    if action == "resume":
        state = await resume_session(db, ctx.user_id, task_id)
        if not state or state.get("error"):
            yield {"event": "message", "data": json.dumps({"content": "Could not find that session."})}
            yield {"event": "done", "data": json.dumps({})}
            return
    else:
        # "start" — load existing prepared session
        state = await get_session_state(db, ctx.user_id, task_id)

    if not state:
        yield {"event": "message", "data": json.dumps({"content": "Session not found. It may have expired."})}
        yield {"event": "done", "data": json.dumps({})}
        return

    phase = state.get("current_phase", "warmup")
    topic = state.get("topic", {})

    if phase == "completed":
        yield {"event": "message", "data": json.dumps({"content": "This session is already completed."})}
        yield {"event": "done", "data": json.dumps({})}
        return

    # Emit phase indicator
    yield {"event": "action", "data": json.dumps({
        "type": "guided_session_phase",
        "phase": phase,
        "task_id": task_id,
        "topic": topic.get("title", ""),
    })}

    # Build phase-specific prompt and override the context
    phase_prompt = build_phase_prompt(phase, topic, state)
    ctx.user_message = phase_prompt
    ctx.intent = _PHASE_TO_INTENT.get(phase, IntentType.LEARN)
    ctx.intent_confidence = 1.0
    ctx.metadata["guided_session"] = {"task_id": task_id, "phase": phase}

    # Route to the appropriate agent and stream
    agent = get_agent(ctx.intent)
    ctx.delegated_agent = agent.name

    ctx = await load_context(ctx, db)

    yield {"event": "status", "data": json.dumps({
        "phase": "generating",
        "intent": ctx.intent.value,
        "agent": agent.name,
        "guided_phase": phase,
    })}

    # Stream agent response
    marker_parser = MarkerParser()
    async for chunk in agent.stream(ctx, db):
        text_chunk = chunk if isinstance(chunk, str) else chunk.get("content", "")
        if text_chunk:
            for event_type, payload in marker_parser.feed(text_chunk):
                if event_type == "text":
                    yield {"event": "message", "data": json.dumps({"content": payload})}
                elif event_type == "action":
                    yield {"event": "action", "data": json.dumps(payload)}

    # Flush remaining
    remaining = marker_parser.flush()
    if remaining:
        yield {"event": "message", "data": json.dumps({"content": remaining})}

    # Persist phase completion and advance to next phase.
    next_state = await advance_phase(db, ctx.user_id, task_id)
    if isinstance(next_state, dict) and not next_state.get("error"):
        completed = next_state.get("completed_phases", [])
        next_phase = next_state.get("current_phase", phase)
    else:
        completed = state.get("completed_phases", []) + [phase]
        next_phase = phase

    # Emit phase progress
    phase_idx = len(completed)
    yield {"event": "action", "data": json.dumps({
        "type": "guided_session_progress",
        "progress": f"{phase_idx}/4",
        "task_id": task_id,
        "next_phase": next_phase,
    })}

    yield {"event": "done", "data": json.dumps({
        "guided_session": phase,
        "task_id": task_id,
        "next_phase": next_phase,
    })}
