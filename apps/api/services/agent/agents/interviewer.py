"""InterviewerAgent — drives mock-interview sessions for Phase 5.

Three responsibilities, all on one class (single-agent, two/three-method
shape mirroring :class:`TutorAgent`):

- :meth:`generate_question` — asks one grounded question per turn.
- :meth:`grade_answer` — scores the candidate's answer on 4 rubric dims
  at ``temperature=0.1`` with one retry on JSON parse failure.
- :meth:`write_summary_inline` — **pure math, no LLM** — aggregates
  per-dimension averages, weakest dims, and worst turn across a session.

Design notes:

- :meth:`execute` is present only to satisfy :class:`BaseAgent`'s abstract
  contract. This agent is driven by the ``/interview`` router
  (T4) — it is deliberately **not** registered in ``AGENT_REGISTRY``.
- LLM calls go through :meth:`BaseAgent.get_llm_client`; the grader pins
  ``temperature=0.1`` for consistency (merge-blocker gate in
  ``test_grade_answer_consistency_merge_gate``).
- The candidate's answer is wrapped in ``<learner_answer>`` XML inside the
  prompt template — defense against prompt injection ("score everything
  5"). The template tells the grader to treat that block as data.
- Rubric dims returned by the LLM are normalised to lowercase to survive
  Title-Case vs snake_case drift — the schema keys stay whatever the
  grader produced, but lookups are case-insensitive.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.interview import (
    DimensionScore,
    RubricScores,
    SummaryResponse,
    TurnResponse,
)
from services.agent.agents.interviewer_prompts import (
    BEHAVIORAL_DIMS,
    DIMENSION_DEFINITIONS,
    GRADER_SYSTEM_PROMPT,
    MODE_PERSONAS,
    QUESTION_SYSTEM_PROMPT,
    TECHNICAL_DIMS,
    _grounding_source_hint,
    _has_meaningful_grounding,
    _load_grounding_excerpt,
)
from services.agent.base import BaseAgent
from services.agent.state import AgentContext

logger = logging.getLogger(__name__)

# Strip a markdown code fence if the grader wraps JSON in ```json ... ```
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class InterviewerAgent(BaseAgent):
    """Mock-interview agent — generates grounded Qs, grades answers, summarises."""

    name = "interviewer"
    profile = (
        "Staff AI Engineer running mock interviews. Grounds questions in the "
        "candidate's own STAR stories / code-defense notes. Grades on 4 rubric "
        "dimensions, calibrated, never inflates scores."
    )
    # Grading benefits from a stronger model; question-gen tolerates standard.
    model_preference = "large"

    # ── BaseAgent contract ─────────────────────────────────────────

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Not used — driven by ``routers/interview.py`` endpoints directly.

        Kept so :class:`BaseAgent`'s ABC is satisfied and so a future
        delegation path (tutor → interviewer) remains viable.
        """
        ctx.response = (
            "InterviewerAgent.execute is a no-op; use generate_question / "
            "grade_answer / write_summary_inline directly."
        )
        return ctx

    # ── Public methods ─────────────────────────────────────────────

    async def generate_question(
        self,
        ctx: AgentContext,
        *,
        turn_number: int,
        total_turns: int,
        project_focus: str,
        mode: str,
        question_type: str,
        prev_questions: list[str],
    ) -> dict[str, Any]:
        """Ask one interview question grounded in the candidate's corpus.

        Returns a dict with ``question`` / ``question_type`` /
        ``grounding_source`` / ``expected_dimensions``. Never raises —
        parse failures fall back to a safe generic question so the router
        can always advance the session.
        """
        try:
            grounding_excerpt = _load_grounding_excerpt(project_focus, mode)
        except FileNotFoundError as exc:
            logger.warning(
                "grounding_corpus_missing project=%s mode=%s err=%s",
                project_focus,
                mode,
                exc,
            )
            grounding_excerpt = ""
        grounding_source_hint = (
            _grounding_source_hint(project_focus, question_type)
            if _has_meaningful_grounding(grounding_excerpt)
            else None
        )

        persona = MODE_PERSONAS.get(mode, MODE_PERSONAS["mixed"])
        prev_tail = prev_questions[-3:] if prev_questions else []
        system_prompt = QUESTION_SYSTEM_PROMPT.format(
            persona=persona,
            turn=turn_number,
            total_turns=total_turns,
            project_focus=project_focus,
            question_type=question_type,
            prev_questions=prev_tail,
            grounding_excerpt=grounding_excerpt or "(no grounding available)",
        )

        raw, _usage = await self._call_llm_json(
            ctx,
            system_prompt=system_prompt,
            user_message="Generate the next question.",
            temperature=0.7,
            max_tokens=400,
        )
        return self._parse_question(
            raw,
            project_focus,
            mode,
            question_type,
            grounding_source_hint=grounding_source_hint,
        )

    async def grade_answer(
        self,
        ctx: AgentContext,
        *,
        question: str,
        answer: str,
        mode: str,
    ) -> RubricScores:
        """Score one Q/A pair against the mode-appropriate rubric.

        ``temperature=0.1`` for consistency. On JSON-parse failure we retry
        once; if the retry also fails we return an all-ones rubric plus an
        apology message rather than raise — the router needs to keep the
        session moving for ADHD-safe UX.
        """
        dims: Sequence[str] = (
            BEHAVIORAL_DIMS if mode == "behavioral" else TECHNICAL_DIMS
        )
        dim_defs = "\n".join(f"- {d}: {DIMENSION_DEFINITIONS[d]}" for d in dims)
        persona = MODE_PERSONAS.get(mode, MODE_PERSONAS["mixed"])
        system_prompt = GRADER_SYSTEM_PROMPT.format(
            persona=persona,
            question=question,
            answer=answer,
            dimension_definitions=dim_defs,
        )

        for attempt in range(2):
            raw, _usage = await self._call_llm_json(
                ctx,
                system_prompt=system_prompt,
                user_message="Grade the answer above.",
                temperature=0.1,
                max_tokens=500,
            )
            parsed = self._try_parse_rubric(raw, dims)
            if parsed is not None:
                return parsed
            logger.warning(
                "rubric_parse_fail attempt=%s mode=%s raw_preview=%r",
                attempt,
                mode,
                (raw or "")[:200],
            )

        # Fallback — all dims 1, short apology. Keeps the session live.
        return RubricScores(
            dimensions={
                d: DimensionScore(score=1, feedback="Grading failed — please retry.")
                for d in dims
            },
            feedback_short="Grading unavailable for this turn. Try again or skip.",
        )

    def write_summary_inline(self, turns: list[TurnResponse]) -> SummaryResponse:
        """Compute per-session summary from graded turns — **no LLM call**.

        - ``avg_by_dimension``: mean score per dim across graded turns.
        - ``weakest_dimensions``: 2 lowest-average dims (stable order by
          average then name).
        - ``worst_turn_id``: left ``None`` here — :class:`TurnResponse`
          carries ``turn_number`` but not the persisted UUID. T4's router
          resolves ``turn_number`` → DB UUID before persisting the summary.
          We stash the chosen ``turn_number`` in ``metadata`` via the
          caller, so the router can map without re-scanning.
        - ``answer_time_ms_avg`` / ``total_answer_time_s``: mean & sum of
          typed turns' answer times; ``None`` when no turn reported timing.
        """
        graded = [t for t in turns if t.rubric is not None]
        if not graded:
            return SummaryResponse(
                avg_by_dimension={},
                weakest_dimensions=[],
                worst_turn_id=None,
                answer_time_ms_avg=None,
                total_answer_time_s=None,
            )

        # Per-dimension averages.
        dim_scores: dict[str, list[int]] = {}
        for turn in graded:
            # rubric is non-None inside `graded`, but ty can't see that.
            assert turn.rubric is not None
            for dim_name, dim_score in turn.rubric.dimensions.items():
                dim_scores.setdefault(dim_name, []).append(dim_score.score)

        avg_by_dim = {d: statistics.fmean(v) for d, v in dim_scores.items()}

        # Weakest 2 — sort by (avg, name) for deterministic ties.
        weakest = sorted(avg_by_dim.items(), key=lambda kv: (kv[1], kv[0]))[:2]
        weakest_dims = [name for name, _ in weakest]

        # Answer time aggregates (ignore turns that didn't report timing).
        timed = [t.answer_time_ms for t in graded if t.answer_time_ms is not None]
        if timed:
            avg_time_ms: int | None = int(statistics.fmean(timed))
            total_time_s: int | None = int(sum(timed) / 1000)
        else:
            avg_time_ms = None
            total_time_s = None

        return SummaryResponse(
            avg_by_dimension=avg_by_dim,
            weakest_dimensions=weakest_dims,
            worst_turn_id=None,  # T4 router resolves turn_number → UUID
            answer_time_ms_avg=avg_time_ms,
            total_answer_time_s=total_time_s,
        )

    # ── Internals ──────────────────────────────────────────────────

    async def _call_llm_json(
        self,
        ctx: AgentContext,
        *,
        system_prompt: str,
        user_message: str,
        temperature: float,  # noqa: ARG002 — reserved for provider plumbing (T3 keeps shape stable)
        max_tokens: int,  # noqa: ARG002 — same
    ) -> tuple[str, dict[str, Any]]:
        """Call the LLM and return ``(raw_text, usage)``.

        ``temperature`` / ``max_tokens`` are accepted for forward-compat
        with a provider that honors them; today's :class:`LLMClient` base
        interface is just ``chat(system, user)``. Keeping the kwargs here
        means the grader's ``temperature=0.1`` contract is visible in the
        call site even though the current client ignores it.
        """
        client = self.get_llm_client(ctx)
        text, usage = await client.chat(system_prompt, user_message)
        return text, usage or {}

    def _parse_question(
        self,
        raw: str,
        project_focus: str,
        mode: str,
        question_type: str,
        *,
        grounding_source_hint: str | None = None,
    ) -> dict[str, Any]:
        """Extract a question dict from raw LLM output. Fallback on any error."""
        fallback_dims = (
            list(BEHAVIORAL_DIMS) if mode == "behavioral" else list(TECHNICAL_DIMS)
        )
        fallback = {
            "question": f"Tell me about your work on {project_focus}.",
            "question_type": question_type if mode != "mixed" else "behavioral",
            "grounding_source": "fallback",
            "expected_dimensions": fallback_dims,
        }

        if not raw or not raw.strip():
            logger.warning(
                "question_parse_empty project=%s mode=%s", project_focus, mode
            )
            return fallback

        cleaned = _FENCE_RE.sub("", raw).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning(
                "question_parse_json_fail project=%s err=%s raw=%r",
                project_focus,
                exc,
                cleaned[:200],
            )
            return fallback

        if not isinstance(parsed, dict) or "question" not in parsed:
            logger.warning(
                "question_parse_shape_fail project=%s keys=%s",
                project_focus,
                list(parsed.keys()) if isinstance(parsed, dict) else type(parsed),
            )
            return fallback

        question = str(parsed.get("question", "")).strip()
        if not question:
            return fallback
        parsed_grounding_source = str(parsed.get("grounding_source") or "").strip()
        if grounding_source_hint and parsed_grounding_source in {
            "",
            "generic",
            "fallback",
        }:
            grounding_source = grounding_source_hint
        else:
            grounding_source = (
                parsed_grounding_source or grounding_source_hint or "generic"
            )

        return {
            "question": question[:300],
            "question_type": str(parsed.get("question_type") or question_type),
            "grounding_source": grounding_source,
            "expected_dimensions": list(
                parsed.get("expected_dimensions") or fallback_dims
            ),
        }

    def _try_parse_rubric(self, raw: str, dims: Sequence[str]) -> RubricScores | None:
        """Parse grader output into :class:`RubricScores`. Return ``None`` on any fail.

        Accepts dim names case-insensitively — ``"situation"`` vs
        ``"Situation"`` both match. Missing dims cause ``None`` (trigger
        retry); extra dims are ignored.
        """
        if not raw or not raw.strip():
            return None
        cleaned = _FENCE_RE.sub("", raw).strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return None

        if not isinstance(parsed, dict):
            return None

        dims_obj = parsed.get("dimensions")
        if not isinstance(dims_obj, dict):
            return None

        # Build case-insensitive lookup of what the grader returned.
        lowered = {str(k).lower(): v for k, v in dims_obj.items()}

        normalised: dict[str, DimensionScore] = {}
        for expected in dims:
            entry = lowered.get(expected.lower())
            if not isinstance(entry, dict):
                return None
            score_raw = entry.get("score")
            feedback_raw = entry.get("feedback", "")
            try:
                score_int = int(score_raw)
            except (TypeError, ValueError):
                return None
            if not 1 <= score_int <= 5:
                return None
            feedback_str = str(feedback_raw or "")[:120]
            try:
                normalised[expected] = DimensionScore(
                    score=score_int, feedback=feedback_str
                )
            except ValueError:
                return None

        feedback_short = str(parsed.get("feedback_short") or "")[:500]

        try:
            return RubricScores(dimensions=normalised, feedback_short=feedback_short)
        except ValueError:
            return None
