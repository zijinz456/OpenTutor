"""Built-in education-domain tools for ReAct agent loop.

These tools give agents factual access to student data, course content,
and code execution. They are the "开箱即用" defaults that non-technical
users get automatically.

Each tool:
- Reads from existing DB models (LearningProgress, WrongAnswer, etc.)
- Returns structured text that the LLM can reason about
- Is read-only (no side effects) except run_code which is sandboxed
"""

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


# ── Tool 1: lookup_progress ──


class LookupProgressTool(Tool):
    """Query student mastery scores and study progress."""

    name = "lookup_progress"
    description = (
        "Look up the student's learning progress and mastery scores. "
        "Returns mastery levels, gap types, and study time for each topic."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="topic",
                type="string",
                description="Optional topic name to filter by (partial match). Leave empty for all topics.",
                required=False,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from models.progress import LearningProgress
        from models.content import CourseContentTree

        try:
            # Join with content tree to get actual topic names
            stmt = (
                select(LearningProgress, CourseContentTree.title)
                .outerjoin(
                    CourseContentTree,
                    LearningProgress.content_node_id == CourseContentTree.id,
                )
                .where(
                    LearningProgress.user_id == ctx.user_id,
                    LearningProgress.course_id == ctx.course_id,
                )
            )
            result = await db.execute(stmt)
            rows = result.all()

            if not rows:
                return ToolResult(success=True, output="No learning progress data found for this student/course.")

            # Filter by topic name if provided
            topic_filter = parameters.get("topic", "").strip().lower()

            lines = []
            for r, title in rows:
                label = title or (str(r.content_node_id)[:8] if r.content_node_id else "general")
                if topic_filter and topic_filter not in label.lower():
                    continue

                mastery_pct = round((r.mastery_score or 0) * 100)
                lines.append(
                    f"- {label}: mastery={mastery_pct}%, status={r.status}, "
                    f"gap={r.gap_type or 'none'}, "
                    f"time={r.time_spent_minutes}min, "
                    f"quiz={r.quiz_correct}/{r.quiz_attempts}"
                )

            if not lines:
                return ToolResult(success=True, output=f"No progress data matching '{topic_filter}'.")

            return ToolResult(success=True, output=f"Student progress ({len(lines)} topics):\n" + "\n".join(lines))

        except Exception as e:
            logger.error("lookup_progress failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


# ── Tool 2: search_content ──


class SearchContentTool(Tool):
    """Run a targeted RAG search against course materials."""

    name = "search_content"
    description = (
        "Search the course materials for specific content. "
        "Use this when the initial context doesn't have enough information "
        "to answer the student's question."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="Search query to find relevant course content.",
                required=True,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from services.search.hybrid import hybrid_search

        query = parameters.get("query", "").strip()
        if not query:
            return ToolResult(success=False, output="", error="Empty search query.")

        try:
            results = await hybrid_search(db, ctx.course_id, query, limit=3)
            if not results:
                return ToolResult(success=True, output="No matching course content found.")

            lines = []
            for i, doc in enumerate(results, 1):
                title = doc.get("title", "Untitled")
                content = doc.get("content", "")[:800]
                score = doc.get("rrf_score", 0)
                lines.append(f"### Result {i}: {title} (score={score:.3f})\n{content}\n")

            return ToolResult(
                success=True,
                output=f"Found {len(results)} relevant sections:\n\n" + "\n".join(lines),
            )
        except Exception as e:
            logger.error("search_content failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


# ── Tool 3: list_wrong_answers ──


class ListWrongAnswersTool(Tool):
    """Query the student's error history and wrong answers."""

    name = "list_wrong_answers"
    description = (
        "List the student's wrong answers with error categories and diagnosis. "
        "Useful for review, error analysis, and identifying weak areas."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="error_category",
                type="string",
                description="Filter by error type.",
                required=False,
                enum=["conceptual", "procedural", "computational", "reading", "careless"],
            ),
            ToolParameter(
                name="mastered",
                type="boolean",
                description="Filter by mastery status. false=still need review, true=already mastered.",
                required=False,
            ),
            ToolParameter(
                name="limit",
                type="integer",
                description="Maximum number of results (default 5).",
                required=False,
                default=5,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from models.ingestion import WrongAnswer

        try:
            stmt = select(WrongAnswer).where(
                WrongAnswer.user_id == ctx.user_id,
                WrongAnswer.course_id == ctx.course_id,
            )

            if parameters.get("error_category"):
                stmt = stmt.where(WrongAnswer.error_category == parameters["error_category"])
            if parameters.get("mastered") is not None:
                stmt = stmt.where(WrongAnswer.mastered == parameters["mastered"])

            limit = min(int(parameters.get("limit", 5)), 20)
            stmt = stmt.order_by(WrongAnswer.created_at.desc()).limit(limit)

            result = await db.execute(stmt)
            rows = result.scalars().all()

            if not rows:
                return ToolResult(success=True, output="No wrong answers found matching the criteria.")

            lines = []
            for r in rows:
                lines.append(
                    f"- Q: {(r.user_answer or '')[:100]}\n"
                    f"  Correct: {(r.correct_answer or '')[:100]}\n"
                    f"  Category: {r.error_category or 'unknown'}, "
                    f"  Diagnosis: {r.diagnosis or 'none'}, "
                    f"  Mastered: {r.mastered}, Reviews: {r.review_count}"
                )

            return ToolResult(
                success=True,
                output=f"Wrong answers ({len(rows)} results):\n" + "\n".join(lines),
            )
        except Exception as e:
            logger.error("list_wrong_answers failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


# ── Tool 4: get_mastery_report ──


class GetMasteryReportTool(Tool):
    """Generate an aggregate learning report for the student."""

    name = "get_mastery_report"
    description = (
        "Generate a comprehensive learning report: overall mastery, "
        "weak areas, study time, quiz accuracy, and error patterns. "
        "No parameters needed — uses the current student and course."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return []

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from models.progress import LearningProgress
        from models.practice import PracticeResult
        from models.ingestion import StudySession, WrongAnswer

        try:
            # Parallel queries
            progress_q = select(LearningProgress).where(
                LearningProgress.user_id == ctx.user_id,
                LearningProgress.course_id == ctx.course_id,
            )
            wrong_stats_q = select(
                WrongAnswer.error_category,
                func.count(WrongAnswer.id),
            ).where(
                WrongAnswer.user_id == ctx.user_id,
                WrongAnswer.course_id == ctx.course_id,
                WrongAnswer.mastered == False,  # noqa: E712
            ).group_by(WrongAnswer.error_category)

            session_q = select(
                func.count(StudySession.id),
                func.sum(StudySession.duration_minutes),
                func.sum(StudySession.problems_attempted),
                func.sum(StudySession.problems_correct),
            ).where(
                StudySession.user_id == ctx.user_id,
                StudySession.course_id == ctx.course_id,
            )

            # Run sequentially — AsyncSession is NOT safe for concurrent use
            progress_res = await db.execute(progress_q)
            wrong_res = await db.execute(wrong_stats_q)
            session_res = await db.execute(session_q)

            progress_rows = progress_res.scalars().all()
            wrong_cats = wrong_res.all()
            session_stats = session_res.one_or_none()

            # Build report
            parts = ["## Learning Report\n"]

            # Overall mastery
            if progress_rows:
                avg_mastery = sum(r.mastery_score or 0 for r in progress_rows) / len(progress_rows)
                mastered_count = sum(1 for r in progress_rows if r.status == "mastered")
                gap_counts = {}
                for r in progress_rows:
                    if r.gap_type:
                        gap_counts[r.gap_type] = gap_counts.get(r.gap_type, 0) + 1

                parts.append(f"**Topics**: {len(progress_rows)} total, {mastered_count} mastered")
                parts.append(f"**Average mastery**: {avg_mastery:.0%}")
                if gap_counts:
                    gap_str = ", ".join(f"{k}: {v}" for k, v in gap_counts.items())
                    parts.append(f"**Gaps**: {gap_str}")
            else:
                parts.append("No progress data yet.")

            # Wrong answer patterns
            if wrong_cats:
                parts.append("\n**Unmastered errors by category**:")
                for cat, count in wrong_cats:
                    parts.append(f"  - {cat or 'unclassified'}: {count}")

            # Study sessions
            if session_stats and session_stats[0]:
                total_sessions, total_minutes, total_attempted, total_correct = session_stats
                accuracy = (total_correct / total_attempted * 100) if total_attempted else 0
                parts.append(f"\n**Study sessions**: {total_sessions}")
                parts.append(f"**Total study time**: {total_minutes or 0} minutes")
                parts.append(f"**Quiz accuracy**: {total_correct or 0}/{total_attempted or 0} ({accuracy:.0f}%)")

            return ToolResult(success=True, output="\n".join(parts))

        except Exception as e:
            logger.error("get_mastery_report failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


# ── Tool 5: run_code ──


class RunCodeTool(Tool):
    """Execute Python code in a safe sandbox."""

    name = "run_code"
    description = (
        "Execute Python code safely and return the output. "
        "Supports math, collections, statistics, and other standard library modules. "
        "Blocks dangerous operations (file I/O, network, system calls)."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="code",
                type="string",
                description="Python code to execute.",
                required=True,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from services.agent.code_execution import CodeExecutionAgent

        code = parameters.get("code", "").strip()
        if not code:
            return ToolResult(success=False, output="", error="No code provided.")

        agent = CodeExecutionAgent()

        # Validate first
        safe, reason = agent._validate_code(code)
        if not safe:
            return ToolResult(success=False, output="", error=f"Unsafe code: {reason}")

        # Execute in thread pool (reuse existing sandbox)
        result = await asyncio.to_thread(agent._execute_safe, code)

        output_parts = []
        if result["output"]:
            output_parts.append(f"Output:\n{result['output']}")
        if result["error"]:
            output_parts.append(f"Error:\n{result['error']}")

        return ToolResult(
            success=result["success"],
            output="\n".join(output_parts) if output_parts else "(no output)",
            error=result["error"] if not result["success"] else None,
        )


# ── Tool 6: check_prerequisites ──


class CheckPrerequisitesTool(Tool):
    """Check if the student has mastered prerequisite knowledge points."""

    name = "check_prerequisites"
    description = (
        "Check if the student has mastered the prerequisites for a given topic. "
        "Returns which prerequisites are met and which have gaps."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="topic",
                type="string",
                description="The topic to check prerequisites for.",
                required=True,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from models.content import CourseContentTree, KnowledgePoint
        from models.progress import LearningProgress

        topic = parameters.get("topic", "").strip()
        if not topic:
            return ToolResult(success=False, output="", error="No topic provided.")

        try:
            # Find knowledge points matching the topic
            kp_result = await db.execute(
                select(KnowledgePoint)
                .where(
                    KnowledgePoint.course_id == ctx.course_id,
                    KnowledgePoint.name.ilike(f"%{topic}%"),
                )
                .limit(5)
            )
            kps = kp_result.scalars().all()

            if not kps:
                return ToolResult(success=True, output=f"No knowledge points found matching '{topic}'.")

            lines = []
            for kp in kps:
                deps = kp.dependencies or []
                if not deps:
                    lines.append(f"- {kp.name}: No prerequisites listed.")
                    continue

                # Check mastery of each prerequisite
                for dep_id in deps:
                    dep_result = await db.execute(
                        select(KnowledgePoint).where(KnowledgePoint.id == dep_id)
                    )
                    dep_kp = dep_result.scalar_one_or_none()
                    dep_name = dep_kp.name if dep_kp else str(dep_id)[:8]

                    prog_result = await db.execute(
                        select(LearningProgress).where(
                            LearningProgress.user_id == ctx.user_id,
                            LearningProgress.course_id == ctx.course_id,
                            LearningProgress.content_node_id == dep_id,
                        )
                    )
                    prog = prog_result.scalar_one_or_none()
                    mastery = prog.mastery_score if prog else 0.0
                    status = "OK" if mastery >= 0.6 else "GAP"
                    lines.append(f"- Prereq for '{kp.name}': {dep_name} — mastery={mastery:.0%} [{status}]")

            return ToolResult(success=True, output=f"Prerequisites check:\n" + "\n".join(lines))

        except Exception as e:
            logger.error("check_prerequisites failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


# ── Tool 7: suggest_related_topics ──


class SuggestRelatedTopicsTool(Tool):
    """Suggest related topics based on knowledge graph connections."""

    name = "suggest_related_topics"
    description = (
        "Find topics related to a given concept based on the course knowledge graph. "
        "Useful for expanding learning or finding connections."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="topic",
                type="string",
                description="The topic to find related concepts for.",
                required=True,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from models.content import KnowledgePoint

        topic = parameters.get("topic", "").strip()
        if not topic:
            return ToolResult(success=False, output="", error="No topic provided.")

        try:
            # Find the knowledge point
            result = await db.execute(
                select(KnowledgePoint)
                .where(
                    KnowledgePoint.course_id == ctx.course_id,
                    KnowledgePoint.name.ilike(f"%{topic}%"),
                )
                .limit(3)
            )
            kps = result.scalars().all()

            if not kps:
                return ToolResult(success=True, output=f"No knowledge points found matching '{topic}'.")

            # Find all KPs that share dependencies or are dependents
            all_related_ids = set()
            for kp in kps:
                if kp.dependencies:
                    all_related_ids.update(kp.dependencies)

            # Also find KPs that depend on these
            for kp in kps:
                dep_result = await db.execute(
                    select(KnowledgePoint).where(
                        KnowledgePoint.course_id == ctx.course_id,
                    )
                )
                all_kps = dep_result.scalars().all()
                for other in all_kps:
                    if other.dependencies and kp.id in (other.dependencies or []):
                        all_related_ids.add(other.id)

            # Load names
            lines = []
            for rid in list(all_related_ids)[:10]:
                r = await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == rid))
                related = r.scalar_one_or_none()
                if related:
                    lines.append(f"- {related.name}")

            if not lines:
                return ToolResult(success=True, output=f"No related topics found for '{topic}' in the knowledge graph.")

            return ToolResult(
                success=True,
                output=f"Related topics for '{topic}':\n" + "\n".join(lines),
            )

        except Exception as e:
            logger.error("suggest_related_topics failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


# ── Tool 8: get_forgetting_forecast ──


class GetForgettingForecastTool(Tool):
    """Get forgetting curve predictions for the student."""

    name = "get_forgetting_forecast"
    description = (
        "Predict which topics the student is about to forget based on FSRS spaced repetition data. "
        "Returns topics sorted by urgency (most at-risk first)."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return []

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        try:
            from services.spaced_repetition.forgetting_forecast import predict_forgetting

            forecast = await predict_forgetting(db, ctx.user_id, ctx.course_id)
            predictions = forecast.get("predictions", [])

            if not predictions:
                return ToolResult(success=True, output="No spaced repetition data available yet.")

            lines = [f"Forgetting forecast ({forecast['total_items']} items, {forecast['urgent_count']} urgent):"]
            for p in predictions[:10]:
                lines.append(
                    f"- {p['title']}: retrievability={p['current_retrievability']:.0%}, "
                    f"drops in {p['days_until_threshold']:.0f} days [{p['urgency']}]"
                )

            return ToolResult(success=True, output="\n".join(lines))

        except Exception as e:
            logger.error("get_forgetting_forecast failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


# ── Registry Helper ──


def get_builtin_tools() -> list[Tool]:
    """Return all built-in education tools for registration."""
    return [
        LookupProgressTool(),
        SearchContentTool(),
        ListWrongAnswersTool(),
        GetMasteryReportTool(),
        RunCodeTool(),
        CheckPrerequisitesTool(),
        SuggestRelatedTopicsTool(),
        GetForgettingForecastTool(),
    ]
