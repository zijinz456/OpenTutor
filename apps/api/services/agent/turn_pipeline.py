"""Helpers for response streaming, verification, and turn packaging."""

from __future__ import annotations

from dataclasses import asdict
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.marker_parser import MarkerParser
from services.agent.state import AgentContext, AgentTurnEnvelope, AgentVerificationResult, IntentType, TaskPhase

logger = logging.getLogger(__name__)


async def consume_agent_stream(ctx: AgentContext, agent: BaseAgent, db: AsyncSession) -> AgentContext:
    """Run an agent through its streaming interface and collect normalized output."""
    parser = MarkerParser()
    content_parts: list[str] = []

    async for chunk in agent.stream(ctx, db):
        for event_type, payload in parser.feed(chunk):
            if event_type == "text":
                content_parts.append(payload)
            elif event_type == "action":
                ctx.actions.append(payload)

    remaining = parser.flush()
    if remaining:
        content_parts.append(remaining)

    cleaned_response = "".join(content_parts).strip()
    if cleaned_response:
        ctx.response = cleaned_response
    return ctx


def finalize_token_usage(ctx: AgentContext, agent: BaseAgent) -> None:
    """Normalize token accounting for direct-stream and ReAct paths."""
    try:
        client = agent.get_llm_client()
        should_add_last_usage = (
            ctx.react_iterations == 0
            or not hasattr(client, "chat_with_tools")
        )
        usage = client.get_last_usage()
        if usage and should_add_last_usage:
            ctx.input_tokens += usage.get("input_tokens", 0)
            ctx.output_tokens += usage.get("output_tokens", 0)
        ctx.total_tokens = ctx.input_tokens + ctx.output_tokens
    except Exception as exc:
        logger.debug("Token tracking unavailable: %s", exc)


def build_provenance(ctx: AgentContext) -> dict:
    """Create a compact provenance summary for UI and persistence."""
    from services.provenance import build_provenance as build_provenance_payload

    payload = build_provenance_payload(
        scene=ctx.scene,
        content_refs=[
            {
                "title": doc.get("title"),
                "source_type": doc.get("source_type"),
                "preview": (doc.get("content") or "")[:140],
            }
            for doc in ctx.content_docs[:3]
            if doc.get("title") or doc.get("content")
        ],
        content_count=len(ctx.content_docs),
        memory_count=len(ctx.memories),
        tool_names=[call.get("tool") for call in ctx.tool_calls[:5] if call.get("tool")],
        action_count=len(ctx.actions),
        generated=True,
        user_input=bool((ctx.user_message or "").strip()),
        source_labels=["generated"],
    )
    payload.update({
        "course_count": len(ctx.content_docs),
        "scene_resolution": ctx.metadata.get("scene_resolution"),
        "scene_policy": ctx.metadata.get("scene_policy"),
        "scene_switch": ctx.metadata.get("scene_switch"),
        "preferences_applied": sorted(ctx.preferences.keys()),
        "preference_sources": ctx.preference_sources,
        "preference_details": [
            {
                "dimension": key,
                "value": value,
                "source": ctx.preference_sources.get(key, "unknown"),
            }
            for key, value in sorted(ctx.preferences.items())
        ],
        "workflow_count": 1 if ctx.metadata.get("workflow_name") else 0,
        "generated_count": 1 if ctx.response else 0,
    })
    return payload


def _get_verifier_result(ctx: AgentContext) -> AgentVerificationResult | None:
    verifier_payload = ctx.metadata.get("verifier")
    if not isinstance(verifier_payload, dict):
        return None
    try:
        return AgentVerificationResult(
            status=verifier_payload["status"],
            code=verifier_payload["code"],
            message=verifier_payload["message"],
            repair_attempted=bool(verifier_payload.get("repair_attempted", False)),
        )
    except KeyError:
        return None


def build_turn_envelope(ctx: AgentContext) -> AgentTurnEnvelope:
    """Build the serializable response envelope for a completed turn."""
    return AgentTurnEnvelope(
        response=ctx.response,
        agent=ctx.delegated_agent or "coordinator",
        intent=ctx.intent.value,
        actions=ctx.actions,
        tool_calls=ctx.tool_calls,
        provenance=ctx.metadata.get("provenance") or build_provenance(ctx),
        verifier=_get_verifier_result(ctx),
        task_link=ctx.metadata.get("task_link"),
    )


def envelope_payload(ctx: AgentContext) -> dict:
    """Return the JSON payload sent to clients when a turn completes."""
    envelope = build_turn_envelope(ctx)
    return {
        "status": "complete",
        "session_id": str(ctx.session_id),
        "response": envelope.response,
        "agent": envelope.agent,
        "intent": envelope.intent,
        "tokens": ctx.total_tokens,
        "actions": envelope.actions,
        "tool_calls": envelope.tool_calls,
        "provenance": envelope.provenance,
        "verifier": asdict(envelope.verifier) if envelope.verifier else None,
        "task_link": envelope.task_link,
        "reflection": ctx.metadata.get("reflection"),
    }


async def apply_verifier(ctx: AgentContext, agent: BaseAgent) -> AgentContext:
    """Run verifier/repair only for the intents that benefit from it."""
    if ctx.intent not in (IntentType.LEARN, IntentType.REVIEW, IntentType.QUIZ, IntentType.PLAN, IntentType.ASSESS):
        return ctx
    try:
        from services.agent.verifier import verify_and_repair

        original_response = ctx.response
        ctx.transition(TaskPhase.VERIFYING)
        ctx.metadata["provenance"] = build_provenance(ctx)
        ctx = await verify_and_repair(ctx, agent)
        ctx.metadata["verifier_replaced"] = ctx.response != original_response
    except Exception as exc:
        logger.warning("Verifier failed (non-critical): %s", exc)
    return ctx


async def apply_reflection(ctx: AgentContext) -> AgentContext:
    """Optionally improve longer substantive answers."""
    verifier_status = (ctx.metadata.get("verifier") or {}).get("status")
    if verifier_status == "failed":
        return ctx
    if not ctx.response or ctx.intent not in (IntentType.LEARN, IntentType.REVIEW) or len(ctx.response) <= 100:
        return ctx
    try:
        original_response = ctx.response
        ctx.transition(TaskPhase.VERIFYING)
        from services.agent.reflection import reflect_and_improve

        ctx = await reflect_and_improve(ctx)
        ctx.metadata["response_replaced"] = (
            ctx.response != original_response
            and ctx.metadata.get("reflection", {}).get("improved")
        )
    except Exception as exc:
        logger.warning("Reflection failed (non-critical): %s", exc)
    return ctx
