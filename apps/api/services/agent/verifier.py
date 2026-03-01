"""Verification rules for structured agent turns."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from services.agent.base import BaseAgent
from services.agent.state import AgentContext, AgentVerificationResult, IntentType

_MATERIAL_DISCLAIMER_PATTERNS = (
    "not in the materials",
    "materials do not cover",
    "i couldn't find",
    "课程材料中没有",
    "材料中未找到",
)


@dataclass
class VerificationIssue:
    code: str
    message: str
    repairable: bool = True


def _contains_material_disclaimer(response: str) -> bool:
    lowered = response.lower()
    return any(pattern in lowered for pattern in _MATERIAL_DISCLAIMER_PATTERNS)


def _looks_like_question_array(response: str) -> bool:
    stripped = response.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def _find_issue(ctx: AgentContext) -> VerificationIssue | None:
    response = (ctx.response or "").strip()
    provenance = ctx.metadata.get("provenance") or {}
    content_count = int(provenance.get("content_count") or len(ctx.content_docs))

    if ctx.intent in (IntentType.LEARN, IntentType.REVIEW):
        if content_count == 0 and response and not _contains_material_disclaimer(response):
            return VerificationIssue(
                code="unsupported_claim_without_materials",
                message="The answer makes course claims without admitting the materials did not cover them.",
            )
        if content_count == 0 and re.search(r"(according to|based on|from) (the )?(course|materials)", response, re.IGNORECASE):
            return VerificationIssue(
                code="claims_course_grounding_without_sources",
                message="The answer cites course materials even though no course material was retrieved.",
                repairable=False,
            )

    if ctx.intent == IntentType.QUIZ and _looks_like_question_array(response):
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            return VerificationIssue(
                code="invalid_question_json",
                message="Generated quiz output must be valid JSON when returning a question array.",
            )

        if not isinstance(parsed, list):
            return VerificationIssue(
                code="question_payload_not_array",
                message="Generated quiz output must be a JSON array.",
            )

        for item in parsed:
            metadata = item.get("problem_metadata") if isinstance(item, dict) else None
            if not isinstance(item, dict) or not isinstance(metadata, dict):
                return VerificationIssue(
                    code="missing_problem_metadata",
                    message="Each generated question must include problem_metadata.",
                )
            if item.get("difficulty_layer") in (None, ""):
                return VerificationIssue(
                    code="missing_difficulty_layer",
                    message="Each generated question must include difficulty_layer.",
                )
            if not metadata.get("core_concept"):
                return VerificationIssue(
                    code="missing_core_concept",
                    message="Each generated question must include problem_metadata.core_concept.",
                )
            if not metadata.get("skill_focus"):
                return VerificationIssue(
                    code="missing_skill_focus",
                    message="Each generated question must include problem_metadata.skill_focus.",
                )

    if ctx.intent == IntentType.PLAN:
        lowered = response.lower()
        has_time_structure = any(token in lowered for token in ("today", "this week", "day-by-day", "daily", "今天", "本周"))
        has_action_items = bool(re.search(r"(^|\n)([-*]|\d+\.)\s+\S+", response))
        if not ctx.tool_calls:
            return VerificationIssue(
                code="planning_without_tools",
                message="Planning answers must consult structured planning tools before returning a study plan.",
            )
        if not has_time_structure or not has_action_items:
            return VerificationIssue(
                code="plan_missing_time_structure",
                message="Study plans must include time buckets and actionable items.",
            )

    if ctx.intent == IntentType.ASSESS:
        lowered = response.lower()
        if "memory" in lowered and "inference" not in lowered and "guess" not in lowered and "推测" not in response:
            return VerificationIssue(
                code="assessment_overstates_memory_evidence",
                message="Assessment answers must distinguish hard evidence from inference.",
            )

    return None


async def _repair_response(agent: BaseAgent, ctx: AgentContext, issue: VerificationIssue) -> bool:
    client = agent.get_llm_client()
    system_prompt = agent.build_system_prompt(ctx)
    repair_prompt = (
        "Revise the prior answer so it satisfies the verifier.\n"
        f"Verifier issue: {issue.code} — {issue.message}\n\n"
        f"User request:\n{ctx.user_message}\n\n"
        f"Current answer:\n{ctx.response}\n\n"
        "Return only the repaired final answer."
    )
    repaired, _ = await client.chat(system_prompt, repair_prompt, images=ctx.images or None)
    repaired = repaired.strip()
    if not repaired:
        return False
    ctx.response = repaired
    return True


async def verify_and_repair(ctx: AgentContext, agent: BaseAgent) -> AgentContext:
    """Apply verification rules and one repair attempt when appropriate."""
    issue = _find_issue(ctx)
    if issue is None:
        ctx.metadata["verifier"] = asdict(
            AgentVerificationResult(status="pass", code="ok", message="Response satisfied verifier checks.")
        )
        return ctx

    if issue.repairable:
        repair_succeeded = False
        try:
            repair_succeeded = await _repair_response(agent, ctx, issue)
        except Exception:
            repair_succeeded = False
        if repair_succeeded and _find_issue(ctx) is None:
            ctx.metadata["verifier"] = asdict(
                AgentVerificationResult(
                    status="repaired",
                    code=issue.code,
                    message=issue.message,
                    repair_attempted=True,
                )
            )
            return ctx

    ctx.metadata["verifier"] = asdict(
        AgentVerificationResult(
            status="failed",
            code=issue.code,
            message=issue.message,
            repair_attempted=issue.repairable,
        )
    )
    return ctx
