"""AssessmentAgent — comprehensive learning evaluation and progress reports.

Borrows from:
- MetaGPT qa_engineer.py: message-driven state machine + round limits
- HelloAgents ReviewerAgent: review feedback loop
- OpenAkita persona dimensions: multi-dimensional evaluation

v4: VCE-inspired cross-type error triangulation.
Key principle: "Aggregation in code (SQL), reasoning by agent."
SQL computes accurate cross-topic error counts; the agent interprets
them and generates actionable recommendations. Numbers injected as
immutable facts — agent never counts errors itself (LLMs miscount).

Provides:
- Knowledge mastery assessment across topics
- Common error pattern analysis
- **Cross-type error triangulation** (systemic vs area-specific weaknesses)
- **Difficulty layer gap analysis** (fundamental / transfer / trap gaps)
- Study effort and consistency metrics
- Personalized improvement recommendations
- Exam readiness estimation
"""

import logging
from collections import defaultdict
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.react_mixin import ReActMixin
from services.agent.state import AgentContext

logger = logging.getLogger(__name__)

# Minimum thresholds for triangulation analysis
_MIN_ERRORS_PER_AREA = 2   # Need ≥2 errors in an area to consider it
_MIN_AREAS_FOR_SYSTEMIC = 2 # Same error in ≥2 areas = systemic


class AssessmentAgent(ReActMixin, BaseAgent):
    """Generates comprehensive learning assessments and progress reports."""

    name = "assessment"
    profile = (
        "You are a learning assessment specialist.\n"
        "Evaluate student progress comprehensively:\n"
        "1. Knowledge mastery across topics (using weighted decay scores)\n"
        "2. Common error patterns — distinguish **systemic** weaknesses\n"
        "   (same error across multiple topics) from **area-specific** ones\n"
        "3. Difficulty layer analysis — where does the student fail?\n"
        "   (Layer 1=basic, Layer 2=application, Layer 3=traps)\n"
        "4. Study effort and consistency metrics\n"
        "5. Personalized improvement recommendations\n"
        "6. Exam readiness estimation\n\n"
        "IMPORTANT: All numbers in the data sections are pre-computed from the\n"
        "database. Do NOT re-count or modify them. Base your analysis on these\n"
        "exact numbers. Use data-driven insights, not just encouragement.\n"
        "Present results clearly with specific numbers and actionable suggestions."
    )
    model_preference = "large"
    react_tools = ["get_mastery_report", "lookup_progress", "list_recent_tasks"]

    async def _build_assessment_data(
        self, ctx: AgentContext, db: AsyncSession,
    ) -> str:
        """Collect learning data from multiple tables for assessment.

        Key design: all aggregation happens here in Python/SQL, producing
        accurate numbers. The agent receives these as immutable facts.
        """
        from models.progress import LearningProgress
        from models.practice import PracticeProblem
        from models.ingestion import WrongAnswer, StudySession

        parts = []

        # 1. Learning progress per content node (with gap type from layer analysis)
        progress_result = await db.execute(
            select(LearningProgress)
            .where(
                LearningProgress.user_id == ctx.user_id,
                LearningProgress.course_id == ctx.course_id,
            )
        )
        progress = progress_result.scalars().all()
        if progress:
            mastered = sum(1 for p in progress if p.mastery_score >= 0.8)
            in_progress = sum(1 for p in progress if 0.2 <= p.mastery_score < 0.8)
            not_started = sum(1 for p in progress if p.mastery_score < 0.2)
            avg_mastery = sum(p.mastery_score for p in progress) / len(progress)
            total_time = sum(p.time_spent_minutes for p in progress)
            total_quizzes = sum(p.quiz_attempts for p in progress)
            total_correct = sum(p.quiz_correct for p in progress)

            parts.append(
                f"## Progress Overview (weighted decay mastery)\n"
                f"- Total topics: {len(progress)}\n"
                f"- Mastered (≥80%): {mastered}\n"
                f"- In progress (20-80%): {in_progress}\n"
                f"- Not started (<20%): {not_started}\n"
                f"- Average mastery: {avg_mastery:.1%}\n"
                f"- Total study time: {total_time} minutes\n"
                f"- Quiz attempts: {total_quizzes}, Correct: {total_correct}"
            )

            # v4: Gap type breakdown from layer progression
            gap_counts = defaultdict(int)
            for p in progress:
                if p.gap_type:
                    gap_counts[p.gap_type] += 1
            if gap_counts:
                gap_str = ", ".join(f"{k}: {v}" for k, v in sorted(gap_counts.items(), key=lambda x: -x[1]))
                parts.append(
                    f"\n## Difficulty Layer Gap Analysis\n"
                    f"- Gap types across topics: {gap_str}\n"
                    f"  (fundamental_gap = fails basic recall, "
                    f"transfer_gap = can't apply knowledge, "
                    f"trap_vulnerability = falls for traps)"
                )
        else:
            parts.append("## Progress Overview\nNo progress data available yet.")

        # 2. Error analysis + v4: cross-type triangulation
        wrong_result = await db.execute(
            select(WrongAnswer, PracticeProblem)
            .join(PracticeProblem, WrongAnswer.problem_id == PracticeProblem.id)
            .where(
                WrongAnswer.user_id == ctx.user_id,
                WrongAnswer.course_id == ctx.course_id,
                WrongAnswer.error_category.isnot(None),
            )
            .order_by(WrongAnswer.created_at.desc())
            .limit(50)
        )
        wrong_rows = wrong_result.all()
        if wrong_rows:
            # Basic error category counts
            error_cats: dict[str, int] = {}
            for wa, _ in wrong_rows:
                cat = wa.error_category or "unknown"
                error_cats[cat] = error_cats.get(cat, 0) + 1
            cat_str = ", ".join(f"{k}: {v}" for k, v in sorted(error_cats.items(), key=lambda x: -x[1]))
            unmastered = sum(1 for wa, _ in wrong_rows if not wa.mastered)
            parts.append(
                f"\n## Error Analysis (database counts — do not modify)\n"
                f"- Total wrong answers analyzed: {len(wrong_rows)}\n"
                f"- Unmastered: {unmastered}\n"
                f"- Error categories: {cat_str}"
            )

            # v4: Cross-type triangulation (SQL aggregation, not LLM)
            # Group by content_node_id → error_category → count
            area_errors: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
            area_totals: dict[str, int] = defaultdict(int)
            for wa, prob in wrong_rows:
                area = str(prob.content_node_id) if prob.content_node_id else "general"
                area_errors[area][wa.error_category] += 1
                area_totals[area] += 1

            # Detect systemic patterns: same error_category in ≥2 areas
            error_area_map: dict[str, list[str]] = defaultdict(list)
            for area, errors in area_errors.items():
                if area_totals[area] < _MIN_ERRORS_PER_AREA:
                    continue
                for cat, count in errors.items():
                    if count >= _MIN_ERRORS_PER_AREA:
                        error_area_map[cat].append(area)

            systemic = {cat: areas for cat, areas in error_area_map.items()
                        if len(areas) >= _MIN_AREAS_FOR_SYSTEMIC}
            area_specific = {cat: areas for cat, areas in error_area_map.items()
                            if len(areas) < _MIN_AREAS_FOR_SYSTEMIC}

            if systemic:
                parts.append(
                    "\n## Systemic Error Patterns (cross-topic — needs targeted intervention)"
                )
                for cat, areas in systemic.items():
                    parts.append(
                        f"- **{cat}** errors appear across {len(areas)} different knowledge areas"
                        f" → This is a SYSTEMIC weakness, not topic-specific."
                    )
                parts.append(
                    "For systemic weaknesses, recommend cross-cutting strategies "
                    "(e.g., calculation drills, reading comprehension exercises)."
                )

            if area_specific:
                parts.append("\n## Area-Specific Weaknesses")
                for cat, areas in area_specific.items():
                    parts.append(
                        f"- **{cat}** errors concentrated in {len(areas)} area(s)"
                        f" → Topic-specific, address with targeted review."
                    )

            # v4: Diagnostic pair results summary
            diagnosed = [(wa, prob) for wa, prob in wrong_rows if wa.diagnosis]
            if diagnosed:
                diag_counts: dict[str, int] = {}
                for wa, _ in diagnosed:
                    diag_counts[wa.diagnosis] = diag_counts.get(wa.diagnosis, 0) + 1
                diag_str = ", ".join(f"{k}: {v}" for k, v in sorted(diag_counts.items(), key=lambda x: -x[1]))
                parts.append(
                    f"\n## Diagnostic Pair Results\n"
                    f"- Diagnosed wrong answers: {len(diagnosed)}\n"
                    f"- Diagnoses: {diag_str}"
                )
        else:
            parts.append("\n## Error Analysis\nNo classified wrong answers recorded.")

        # 3. Study sessions (effort & consistency)
        session_result = await db.execute(
            select(StudySession)
            .where(
                StudySession.user_id == ctx.user_id,
                StudySession.course_id == ctx.course_id,
            )
            .order_by(StudySession.started_at.desc())
            .limit(30)
        )
        sessions = session_result.scalars().all()
        if sessions:
            total_sessions = len(sessions)
            total_duration = sum(s.duration_minutes or 0 for s in sessions)
            total_problems = sum(s.problems_attempted for s in sessions)
            total_correct = sum(s.problems_correct for s in sessions)
            avg_duration = total_duration / total_sessions if total_sessions else 0

            parts.append(
                f"\n## Study Sessions (last {total_sessions})\n"
                f"- Total study time: {total_duration} minutes\n"
                f"- Average session: {avg_duration:.0f} minutes\n"
                f"- Problems attempted: {total_problems}\n"
                f"- Problems correct: {total_correct}\n"
                + (f"- Accuracy: {total_correct / total_problems:.1%}" if total_problems else "")
            )
        else:
            parts.append("\n## Study Sessions\nNo session data available.")

        return "\n".join(parts)

    def build_system_prompt(self, ctx: AgentContext) -> str:
        """Assessment-specific prompt with pre-loaded assessment data."""
        base = super().build_system_prompt(ctx)
        assessment_data = ctx.metadata.get("assessment_data", "")
        if assessment_data:
            return f"{base}\n\n{assessment_data}"
        return base

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Generate comprehensive learning assessment."""
        ctx.metadata["assessment_data"] = await self._build_assessment_data(ctx, db)
        system_prompt = self.build_system_prompt(ctx)
        client = self.get_llm_client()
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message)
        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Pre-load assessment data, then delegate to ReActMixin.stream()."""
        ctx.metadata["assessment_data"] = await self._build_assessment_data(ctx, db)
        async for chunk in ReActMixin.stream(self, ctx, db):
            yield chunk
