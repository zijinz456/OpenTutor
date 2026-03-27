"""Helpers for response streaming, verification, and turn packaging."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.marker_parser import MarkerParser
from services.agent.state import AgentContext, AgentTurnEnvelope, AgentVerificationResult, IntentType, TaskPhase

logger = logging.getLogger(__name__)

_VERIFIER_BUDGET_SECONDS = 12
_REFLECTION_BUDGET_SECONDS = 15
_SHORT_TURN_MAX_REQUEST_CHARS = 90
_SHORT_TURN_MAX_RESPONSE_CHARS = 240


def _record_stream_warning(ctx: AgentContext, warning_type: str, message: str) -> None:
    warnings = ctx.metadata.setdefault("stream_warnings", [])
    if not isinstance(warnings, list):
        warnings = []
        ctx.metadata["stream_warnings"] = warnings
    if any(item.get("type") == warning_type for item in warnings if isinstance(item, dict)):
        return
    warnings.append({"type": warning_type, "message": message})


def _turn_elapsed_seconds(ctx: AgentContext) -> float:
    return max(0.0, time.time() - ctx.created_at)


def _build_content_evidence_groups(content_docs: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}

    for doc in content_docs[:5]:
        if not isinstance(doc, dict):
            continue
        facets = [str(item) for item in (doc.get("matched_facets") or []) if item]
        terms = [str(item) for item in (doc.get("matched_terms") or []) if item]
        source_file = str(doc.get("source_file") or "").strip()
        label = facets[0] if facets else (terms[0] if terms else str(doc.get("title") or "Course evidence").strip())
        normalized_label = label.lower()[:120]
        key = f"{source_file}|{normalized_label}"

        group = groups.get(key)
        if group is None:
            group = {
                "label": label,
                "titles": [],
                "matched_terms": [],
                "matched_facets": [],
                "section_count": 0,
                "summary_candidates": [],
            }
            groups[key] = group

        title = str(doc.get("title") or "").strip()
        if title and title not in group["titles"]:
            group["titles"].append(title)

        for item in facets:
            if item not in group["matched_facets"]:
                group["matched_facets"].append(item)

        for item in terms:
            if item not in group["matched_terms"]:
                group["matched_terms"].append(item)

        summary = str(doc.get("evidence_summary") or doc.get("content") or "").strip()
        if summary:
            group["summary_candidates"].append(summary)

        group["section_count"] += int(doc.get("section_hit_count") or 1)

    ranked_groups: list[dict] = []
    for group in groups.values():
        summary_counts = Counter(group.pop("summary_candidates", []))
        summary = summary_counts.most_common(1)[0][0] if summary_counts else ""
        ranked_groups.append({
            "label": group["label"],
            "titles": group["titles"][:3],
            "matched_terms": group["matched_terms"][:6],
            "matched_facets": group["matched_facets"][:4],
            "section_count": group["section_count"],
            "summary": summary[:320] if summary else None,
        })

    ranked_groups.sort(
        key=lambda item: (
            int(item.get("section_count") or 0),
            len(item.get("matched_facets") or []),
            len(item.get("matched_terms") or []),
        ),
        reverse=True,
    )
    return ranked_groups[:3]


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
    except (AttributeError, KeyError, TypeError) as exc:
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
                "evidence_summary": doc.get("evidence_summary"),
                "matched_terms": list(doc.get("matched_terms") or [])[:6],
                "matched_facets": list(doc.get("matched_facets") or [])[:4],
                "section_hit_count": doc.get("section_hit_count"),
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
        extra={
            "content_evidence_groups": _build_content_evidence_groups(ctx.content_docs),
        },
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
        "verifier_diagnostics": ctx.metadata.get("verifier_diagnostics"),
        "task_link": envelope.task_link,
        "reflection": ctx.metadata.get("reflection"),
        "layout_simplification": ctx.metadata.get("layout_simplification"),
        "is_mock": ctx.metadata.get("is_mock", False),
    }


async def apply_verifier(ctx: AgentContext, agent: BaseAgent) -> AgentContext:
    """Run verifier/repair only for the intents that benefit from it."""
    if ctx.intent not in (IntentType.LEARN, IntentType.PLAN, IntentType.GENERAL):
        return ctx
    elapsed = _turn_elapsed_seconds(ctx)
    if elapsed >= _VERIFIER_BUDGET_SECONDS:
        _record_stream_warning(
            ctx,
            "slow_response",
            "This reply is taking longer than usual, so some extra checks were skipped to keep things moving.",
        )
        _record_stream_warning(
            ctx,
            "verification_skipped",
            "Final verification was skipped for this turn to avoid adding more delay.",
        )
        return ctx
    try:
        from services.agent.verifier import verify_and_repair

        original_response = ctx.response
        ctx.transition(TaskPhase.VERIFYING)
        # Provenance is built by the caller after all post-processing;
        # no need to rebuild here.
        ctx = await verify_and_repair(ctx, agent)
        ctx.metadata["verifier_replaced"] = ctx.response != original_response
    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
        logger.exception("Verifier failed (non-critical): %s", exc)
        _record_stream_warning(
            ctx,
            "verification_skipped",
            "Final verification was unavailable for this reply, so the first draft was kept.",
        )
    return ctx


async def apply_reflection(ctx: AgentContext) -> AgentContext:
    """Optionally improve longer substantive answers."""
    verifier_status = (ctx.metadata.get("verifier") or {}).get("status")
    if verifier_status == "failed":
        return ctx
    if not ctx.response or ctx.intent not in (IntentType.LEARN, IntentType.GENERAL) or len(ctx.response) <= 100:
        return ctx
    elapsed = _turn_elapsed_seconds(ctx)
    if elapsed >= _REFLECTION_BUDGET_SECONDS:
        _record_stream_warning(
            ctx,
            "adaptation_degraded",
            "Advanced adaptation is temporarily unavailable for this reply. I'll keep helping, but some polishing was skipped.",
        )
        _record_stream_warning(
            ctx,
            "slow_response",
            "This reply is taking longer than usual, so extra polishing was skipped.",
        )
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
    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
        logger.exception("Reflection failed (non-critical): %s", exc)
        _record_stream_warning(
            ctx,
            "adaptation_degraded",
            "Advanced adaptation is temporarily unavailable for this reply. I'll keep helping with the current answer.",
        )
    return ctx
