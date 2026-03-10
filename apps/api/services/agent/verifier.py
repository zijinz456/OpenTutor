"""Verification rules for structured agent turns."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass

from services.agent.base import BaseAgent
from services.agent.state import AgentContext, AgentVerificationResult, IntentType

logger = logging.getLogger(__name__)

_MATERIAL_DISCLAIMER_PATTERNS = (
    "not in the materials",
    "materials do not cover",
    "i couldn't find",
    "not found in the materials",
    "course materials do not contain",
)

_GENERIC_NONANSWER_PATTERNS = (
    "i can help with that",
    "let's work through it",
    "we can work through it",
    "here's a breakdown",
    "let me know if you'd like",
    "i'd be happy to help",
)

# Patterns that indicate the tutor gave a direct answer instead of guiding discovery.
# These fire when the response hands over the solution without asking the student to think.
_DIRECT_ANSWER_PATTERNS = (
    "the answer is",
    "the correct answer is",
    "the solution is",
    "here is the answer",
    "here's the answer",
    "the result is",
    "this equals",
    "this gives us",
    "therefore the answer",
    "so the answer is",
    "which gives us the final answer",
)

# Counter-patterns: if these appear alongside a direct-answer pattern, the tutor
# is likely still guiding (e.g. "what do you think the answer is?")
_SOCRATIC_COUNTER_PATTERNS = (
    "what do you think",
    "can you explain",
    "why do you think",
    "how would you",
    "what would happen",
    "try to",
    "let's think about",
    "does that make sense",
    "what if",
    "how does this relate",
    "can you see why",
    "before i reveal",
    "take a moment",
)
_STOPWORDS = {
    "a", "an", "and", "are", "be", "can", "do", "for", "from", "help", "how", "i",
    "explain", "in", "is", "it", "me", "my", "of", "on", "or", "please", "review",
    "show", "study", "tell", "that", "the", "this", "to", "what", "why", "with", "you",
}


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


def _salient_terms(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_\-]{2,}", text or "")
        if token.lower() not in _STOPWORDS
    }


def _looks_like_generic_nonanswer(response: str) -> bool:
    lowered = response.lower()
    return any(pattern in lowered for pattern in _GENERIC_NONANSWER_PATTERNS)


def _collect_evidence_terms(ctx: AgentContext, limit: int = 18) -> list[str]:
    counter: Counter[str] = Counter()
    texts: list[str] = []
    provenance = ctx.metadata.get("provenance") or {}

    for ref in provenance.get("content_refs") or []:
        if isinstance(ref, dict):
            texts.append(str(ref.get("title") or ""))
            texts.append(str(ref.get("preview") or ""))

    for doc in ctx.content_docs[:4]:
        if isinstance(doc, dict):
            texts.append(str(doc.get("title") or ""))
            texts.append(str(doc.get("content") or "")[:300])

    for text in texts:
        for token in _salient_terms(text):
            counter[token] += 1

    return [token for token, _count in counter.most_common(limit)]


def _acceptance_signals(ctx: AgentContext) -> dict[str, object]:
    response = (ctx.response or "").strip()
    provenance = ctx.metadata.get("provenance") or {}
    content_count = int(provenance.get("content_count") or len(ctx.content_docs))
    request_terms = _salient_terms(ctx.user_message)
    response_terms = _salient_terms(response)
    evidence_terms = set(_collect_evidence_terms(ctx))
    request_overlap = request_terms & response_terms
    evidence_overlap = evidence_terms & response_terms

    request_coverage = round(len(request_overlap) / max(len(request_terms), 1), 3)
    evidence_coverage = round(len(evidence_overlap) / max(len(evidence_terms), 1), 3) if evidence_terms else 0.0

    return {
        "content_count": content_count,
        "request_terms": sorted(request_terms)[:16],
        "response_terms": sorted(response_terms)[:20],
        "evidence_terms": sorted(evidence_terms)[:20],
        "request_overlap_terms": sorted(request_overlap)[:12],
        "evidence_overlap_terms": sorted(evidence_overlap)[:12],
        "request_coverage": request_coverage,
        "evidence_coverage": evidence_coverage,
    }


def _find_issue(ctx: AgentContext, signals: dict[str, object]) -> VerificationIssue | None:
    response = (ctx.response or "").strip()
    content_count = int(signals.get("content_count") or 0)
    request_terms = set(signals.get("request_terms") or [])
    request_overlap = set(signals.get("request_overlap_terms") or [])
    request_coverage = float(signals.get("request_coverage") or 0.0)
    evidence_terms = set(signals.get("evidence_terms") or [])
    evidence_overlap = set(signals.get("evidence_overlap_terms") or [])
    evidence_coverage = float(signals.get("evidence_coverage") or 0.0)

    if ctx.intent in (IntentType.LEARN, IntentType.GENERAL):
        if (
            response
            and len(response) < 220
            and len(request_terms) >= 2
            and len(request_overlap) == 0
            and _looks_like_generic_nonanswer(response)
        ):
            return VerificationIssue(
                code="response_does_not_address_request",
                message="The answer sounds helpful but does not clearly address the student's actual topic.",
            )
        if (
            response
            and len(request_terms) >= 3
            and len(response) < 360
            and request_coverage < 0.3
        ):
            return VerificationIssue(
                code="response_misses_requested_points",
                message="The answer does not cover enough of the student's requested points to count as completed help.",
            )
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
        if (
            content_count > 0
            and evidence_terms
            and response
            and len(response) < 420
            and request_coverage < 0.45
            and evidence_coverage < 0.12
            and not evidence_overlap
        ):
            return VerificationIssue(
                code="answer_lacks_evidence_coverage",
                message="The answer does not clearly use the retrieved course evidence needed for the student's request.",
            )

    # Socratic violation: tutor gives direct answers instead of guiding discovery.
    # Only triggers for learning-intent responses that are explanatory (not quiz JSON,
    # not assessment reports, not tool-heavy responses).
    if (
        ctx.intent == IntentType.LEARN
        and response
        and not _looks_like_question_array(response)
        and not any(kw in ctx.user_message.lower() for kw in ("assessment", "progress report", "how am i doing", "mastery"))
    ):
        lowered_resp = response.lower()
        has_direct_answer = any(p in lowered_resp for p in _DIRECT_ANSWER_PATTERNS)
        has_socratic_counter = any(p in lowered_resp for p in _SOCRATIC_COUNTER_PATTERNS)
        # Only flag if the tutor gives a direct answer WITHOUT any Socratic follow-up
        if has_direct_answer and not has_socratic_counter:
            return VerificationIssue(
                code="socratic_violation_direct_answer",
                message=(
                    "The tutor gave a direct answer instead of guiding the student to discover it. "
                    "Rephrase to ask a leading question that helps the student reach the answer themselves."
                ),
            )

    if ctx.intent == IntentType.LEARN and _looks_like_question_array(response):
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
        has_time_structure = any(token in lowered for token in ("today", "this week", "day-by-day", "daily", "tomorrow", "next week"))
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

    if ctx.intent == IntentType.LEARN and any(kw in ctx.user_message.lower() for kw in ("assessment", "progress report", "how am i doing", "mastery")):
        lowered = response.lower()
        if "memory" in lowered and "inference" not in lowered and "guess" not in lowered and "speculation" not in lowered:
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
    signals = _acceptance_signals(ctx)
    ctx.metadata["verifier_diagnostics"] = signals
    issue = _find_issue(ctx, signals)
    if issue is None:
        ctx.metadata["verifier"] = asdict(
            AgentVerificationResult(status="pass", code="ok", message="Response satisfied verifier checks.")
        )
        return ctx

    if issue.repairable:
        repair_succeeded = False
        try:
            repair_succeeded = await _repair_response(agent, ctx, issue)
        except (ConnectionError, TimeoutError, ValueError, RuntimeError):
            logger.debug("Verifier repair attempt failed for issue %s", issue.code, exc_info=True)
            repair_succeeded = False
        if repair_succeeded:
            repaired_signals = _acceptance_signals(ctx)
            ctx.metadata["verifier_diagnostics"] = repaired_signals
        if repair_succeeded and _find_issue(ctx, ctx.metadata.get("verifier_diagnostics") or {}) is None:
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
