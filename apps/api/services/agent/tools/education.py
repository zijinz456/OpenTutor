"""Built-in education-domain tools for ReAct agent loop.

Tools are classified by side-effect category:
- READ:    No side effects (search, lookup, list)
- WRITE:   Creates / mutates data (generate flashcards, quiz, notes, plan)
- COMPUTE: Sandboxed computation (run_code)

Write tools:
- Use db.flush() (not commit) — orchestrator commits atomically after streaming.
- Support idempotency via ToolCategory.WRITE base-class dedup.
- Emit ctx.emit_progress() events for frontend progress display.
- Emit ctx.actions for frontend section refresh after successful flush.
"""

import asyncio
import json
import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolCategory, ToolParameter, ToolResult

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
    category = ToolCategory.COMPUTE
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

            # Collect IDs from dependencies (upstream)
            all_related_ids = set()
            source_ids = {kp.id for kp in kps}
            for kp in kps:
                if kp.dependencies:
                    all_related_ids.update(kp.dependencies)

            # Single query to find reverse dependents (downstream) — avoids N+1
            all_course_kps = await db.execute(
                select(KnowledgePoint).where(
                    KnowledgePoint.course_id == ctx.course_id,
                )
            )
            for other in all_course_kps.scalars().all():
                if other.dependencies:
                    if source_ids & set(other.dependencies):
                        all_related_ids.add(other.id)

            # Remove self-references
            all_related_ids -= source_ids

            # Single batch query to load related KP names — avoids N+1
            lines = []
            if all_related_ids:
                related_result = await db.execute(
                    select(KnowledgePoint).where(
                        KnowledgePoint.id.in_(list(all_related_ids)[:10])
                    )
                )
                for related in related_result.scalars().all():
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


class GetCourseOutlineTool(Tool):
    """Return a compact top-level course outline."""

    name = "get_course_outline"
    description = (
        "Return the top-level course outline from the course content tree. "
        "Useful for planning, curriculum analysis, and grounding answers in structure."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return []

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from models.content import CourseContentTree

        try:
            result = await db.execute(
                select(CourseContentTree)
                .where(CourseContentTree.course_id == ctx.course_id)
                .order_by(CourseContentTree.level.asc(), CourseContentTree.order_index.asc(), CourseContentTree.created_at.asc())
                .limit(30)
            )
            nodes = result.scalars().all()
            if not nodes:
                return ToolResult(success=True, output="No course outline is available yet.")

            lines = []
            for node in nodes:
                if node.level > 2:
                    continue
                indent = "  " * node.level
                lines.append(f"{indent}- {node.title}")

            return ToolResult(success=True, output="Course outline:\n" + "\n".join(lines[:20]))
        except Exception as e:
            logger.error("get_course_outline failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


class ListStudyGoalsTool(Tool):
    """Return active or historical study goals."""

    name = "list_study_goals"
    description = "List the student's study goals for the current course."
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="status",
                type="string",
                description="Optional goal status filter.",
                required=False,
                enum=["active", "paused", "completed"],
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from models.study_goal import StudyGoal

        try:
            stmt = (
                select(StudyGoal)
                .where(
                    StudyGoal.user_id == ctx.user_id,
                    StudyGoal.course_id == ctx.course_id,
                )
                .order_by(StudyGoal.updated_at.desc(), StudyGoal.created_at.desc())
            )
            if parameters.get("status"):
                stmt = stmt.where(StudyGoal.status == parameters["status"])

            result = await db.execute(stmt.limit(10))
            goals = result.scalars().all()
            if not goals:
                return ToolResult(success=True, output="No study goals found for this course.")

            lines = [
                f"- {goal.title}: status={goal.status}, next_action={goal.next_action or 'not set'}, target={goal.target_date or 'none'}"
                for goal in goals
            ]
            return ToolResult(success=True, output="Study goals:\n" + "\n".join(lines))
        except Exception as e:
            logger.error("list_study_goals failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


class ListRecentTasksTool(Tool):
    """Return recent durable tasks for the current course."""

    name = "list_recent_tasks"
    description = "List recent durable agent tasks, including approvals and failures."
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="limit",
                type="integer",
                description="Maximum number of tasks to return.",
                required=False,
                default=5,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from models.agent_task import AgentTask

        try:
            limit = min(int(parameters.get("limit", 5)), 10)
            result = await db.execute(
                select(AgentTask)
                .where(
                    AgentTask.user_id == ctx.user_id,
                    AgentTask.course_id == ctx.course_id,
                )
                .order_by(AgentTask.updated_at.desc(), AgentTask.created_at.desc())
                .limit(limit)
            )
            tasks = result.scalars().all()
            if not tasks:
                return ToolResult(success=True, output="No recent tasks found.")

            lines = [
                f"- {task.title}: type={task.task_type}, status={task.status}, attempts={task.attempts}/{task.max_attempts}"
                for task in tasks
            ]
            return ToolResult(success=True, output="Recent tasks:\n" + "\n".join(lines))
        except Exception as e:
            logger.error("list_recent_tasks failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


class ListAssignmentsTool(Tool):
    """Return assignments/exams extracted from ingestion."""

    name = "list_assignments"
    description = "List assignments, quizzes, or exams associated with the course."
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="limit",
                type="integer",
                description="Maximum number of assignments to return.",
                required=False,
                default=10,
            ),
            ToolParameter(
                name="include_completed",
                type="boolean",
                description="Whether to include completed assignments.",
                required=False,
                default=False,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from models.ingestion import Assignment

        try:
            limit = min(int(parameters.get("limit", 10)), 20)
            include_completed = bool(parameters.get("include_completed", False))

            stmt = (
                select(Assignment)
                .where(Assignment.course_id == ctx.course_id)
                .order_by(Assignment.created_at.desc())
            )
            if not include_completed:
                stmt = stmt.where(Assignment.status != "completed")

            result = await db.execute(stmt.limit(limit))
            assignments = result.scalars().all()
            if not assignments:
                return ToolResult(success=True, output="No assignments found for this course.")

            lines = [
                f"- {assignment.title}: type={assignment.assignment_type or 'general'}, status={assignment.status}, due={assignment.due_date or 'unspecified'}"
                for assignment in assignments
            ]
            return ToolResult(success=True, output="Assignments:\n" + "\n".join(lines))
        except Exception as e:
            logger.error("list_assignments failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


# ── Tool 13: generate_flashcards (write) ──


class GenerateFlashcardsTool(Tool):
    """Generate flashcards from course content and save them."""

    name = "generate_flashcards"
    category = ToolCategory.WRITE
    description = (
        "Generate spaced-repetition flashcards from course materials. "
        "Creates cards with question/answer pairs and saves them for review. "
        "Use when the student asks for flashcards or study cards."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="count",
                type="integer",
                description="Number of flashcards to generate (1-20). Default 5.",
                required=False,
                default=5,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        try:
            count = min(max(int(parameters.get("count", 5)), 1), 20)

            ctx.emit_progress(self.name, "Analysing course content...", step=1, total=3)

            from services.spaced_repetition.flashcards import generate_flashcards

            cards = await generate_flashcards(db, ctx.course_id, count=count)

            if not cards:
                return ToolResult(success=True, output="No flashcards could be generated. The course may lack sufficient content.")

            ctx.emit_progress(self.name, f"Saving {len(cards)} flashcards...", step=2, total=3)

            from services.generated_assets import save_generated_asset

            await save_generated_asset(
                db,
                user_id=ctx.user_id,
                course_id=ctx.course_id,
                asset_type="flashcards",
                title="AI-Generated Flashcards",
                content={"cards": cards},
                metadata={"count": len(cards)},
            )
            await db.flush()

            ctx.emit_progress(self.name, "Done", step=3, total=3)
            ctx.actions.append({"action": "data_updated", "value": "practice"})

            summary_lines = [f"- Q: {c.get('front', '')[:60]}..." for c in cards[:5]]
            return ToolResult(
                success=True,
                output=f"Generated {len(cards)} flashcards:\n" + "\n".join(summary_lines),
            )
        except Exception as e:
            await db.rollback()
            logger.error("generate_flashcards tool failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


# ── Tool 14: generate_quiz (write) ──


class GenerateQuizTool(Tool):
    """Generate quiz questions from course content."""

    name = "generate_quiz"
    category = ToolCategory.WRITE
    description = (
        "Generate practice quiz questions from course materials. "
        "Creates multiple-choice, true/false, or short-answer questions and saves them. "
        "Use when the student asks for quiz questions, practice problems, or test prep."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="topic",
                type="string",
                description="Optional topic to focus questions on. Leave empty for general questions.",
                required=False,
            ),
            ToolParameter(
                name="count",
                type="integer",
                description="Number of questions to generate (1-10). Default 3.",
                required=False,
                default=3,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        try:
            topic = parameters.get("topic", "").strip()
            count = min(max(int(parameters.get("count", 3)), 1), 10)

            ctx.emit_progress(self.name, "Searching course content...", step=1, total=3)

            from services.search.hybrid import hybrid_search

            query = topic or "key concepts"
            results = await hybrid_search(db, ctx.course_id, query, limit=3)
            if not results:
                return ToolResult(success=True, output="No course content found to generate questions from.")

            content = "\n\n".join(r.get("content", "")[:2000] for r in results)
            title = topic or results[0].get("title", "Course Content")

            ctx.emit_progress(self.name, "Generating questions...", step=2, total=3)

            from services.parser.quiz import extract_questions

            problems = await extract_questions(content, title, ctx.course_id)

            if not problems:
                return ToolResult(success=True, output="No questions could be extracted from the content.")

            problems = problems[:count]
            for p in problems:
                db.add(p)
            await db.flush()

            ctx.emit_progress(self.name, "Done", step=3, total=3)
            ctx.actions.append({"action": "data_updated", "value": "practice"})

            summary_lines = [
                f"- [{p.question_type}] {(p.question or '')[:60]}..."
                for p in problems
            ]
            return ToolResult(
                success=True,
                output=f"Generated {len(problems)} quiz questions:\n" + "\n".join(summary_lines),
            )
        except Exception as e:
            await db.rollback()
            logger.error("generate_quiz tool failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


# ── Tool 15: generate_notes (write) ──


class GenerateNotesTool(Tool):
    """Generate structured notes from course content."""

    name = "generate_notes"
    category = ToolCategory.WRITE
    description = (
        "Generate structured study notes from course materials in various formats. "
        "Supports bullet points, tables, mind maps, step-by-step, and summaries. "
        "Use when the student asks for notes, summaries, or study guides."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="topic",
                type="string",
                description="Topic to generate notes about.",
                required=True,
            ),
            ToolParameter(
                name="format",
                type="string",
                description="Note format: bullet_point, table, mind_map, step_by_step, or summary.",
                required=False,
                default="bullet_point",
                enum=["bullet_point", "table", "mind_map", "step_by_step", "summary"],
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        try:
            topic = parameters.get("topic", "").strip()
            if not topic:
                return ToolResult(success=False, output="", error="Topic is required.")

            note_format = parameters.get("format", "bullet_point")

            ctx.emit_progress(self.name, f"Searching content for '{topic}'...", step=1, total=3)

            from services.search.hybrid import hybrid_search

            results = await hybrid_search(db, ctx.course_id, topic, limit=5)
            if not results:
                return ToolResult(success=True, output=f"No course content found for topic '{topic}'.")

            content = "\n\n".join(r.get("content", "")[:2000] for r in results)
            title = topic

            ctx.emit_progress(self.name, f"Generating {note_format} notes...", step=2, total=3)

            from services.parser.notes import restructure_notes

            notes_md = await restructure_notes(content, title, note_format=note_format)

            if not notes_md or not notes_md.strip():
                return ToolResult(success=True, output="Could not generate notes from the available content.")

            from services.generated_assets import save_generated_asset

            await save_generated_asset(
                db,
                user_id=ctx.user_id,
                course_id=ctx.course_id,
                asset_type="notes",
                title=f"Notes: {title}",
                content={"markdown": notes_md, "format": note_format},
                metadata={"topic": topic, "format": note_format},
            )
            await db.flush()

            ctx.emit_progress(self.name, "Done", step=3, total=3)
            ctx.actions.append({"action": "data_updated", "value": "notes"})

            preview = notes_md[:300] + ("..." if len(notes_md) > 300 else "")
            return ToolResult(
                success=True,
                output=f"Generated {note_format} notes for '{topic}':\n\n{preview}",
            )
        except Exception as e:
            await db.rollback()
            logger.error("generate_notes tool failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


# ── Tool 16: create_study_plan (write) ──


class CreateStudyPlanTool(Tool):
    """Create a study/exam prep plan."""

    name = "create_study_plan"
    category = ToolCategory.WRITE
    description = (
        "Create a personalized study plan or exam preparation plan. "
        "Analyzes the student's progress and generates a day-by-day schedule. "
        "Use when the student asks for a study plan, exam prep, or revision schedule."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="exam_topic",
                type="string",
                description="Optional specific exam topic to focus on.",
                required=False,
            ),
            ToolParameter(
                name="days_until_exam",
                type="integer",
                description="Number of days until the exam (1-90). Default 7.",
                required=False,
                default=7,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        try:
            exam_topic = parameters.get("exam_topic", "").strip() or None
            days = min(max(int(parameters.get("days_until_exam", 7)), 1), 90)

            ctx.emit_progress(self.name, "Assessing readiness...", step=1, total=3)

            from services.workflow.exam_prep import run_exam_prep

            result = await run_exam_prep(
                db, ctx.user_id, ctx.course_id,
                exam_topic=exam_topic,
                days_until_exam=days,
            )

            plan_md = result.get("plan", "")
            if not plan_md:
                return ToolResult(success=True, output="Could not generate a study plan.")

            ctx.emit_progress(self.name, "Saving study plan...", step=2, total=3)

            from services.generated_assets import save_generated_asset

            await save_generated_asset(
                db,
                user_id=ctx.user_id,
                course_id=ctx.course_id,
                asset_type="study_plan",
                title=f"{'Exam Prep' if exam_topic else 'Study'} Plan ({days} days)",
                content={"markdown": plan_md, "readiness": result.get("readiness")},
                metadata={
                    "days_until_exam": days,
                    "exam_topic": exam_topic,
                    "topics_count": result.get("topics_count", 0),
                },
            )
            await db.flush()

            ctx.emit_progress(self.name, "Done", step=3, total=3)
            ctx.actions.append({"action": "data_updated", "value": "plan"})

            preview = plan_md[:400] + ("..." if len(plan_md) > 400 else "")
            return ToolResult(
                success=True,
                output=f"Created {days}-day study plan:\n\n{preview}",
            )
        except Exception as e:
            await db.rollback()
            logger.error("create_study_plan tool failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


# ── Tool 17: derive_diagnostic (write) ──


class DeriveDiagnosticTool(Tool):
    """Generate a simplified diagnostic question from a wrong answer."""

    name = "derive_diagnostic"
    category = ToolCategory.WRITE
    description = (
        "Generate a simplified diagnostic follow-up question based on a student's wrong answer. "
        "The diagnostic version removes traps/distractors while preserving the core concept, "
        "helping determine if the error was due to a concept gap or carelessness. "
        "Use when reviewing wrong answers and wanting to create targeted follow-up practice."
    )
    domain = "education"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="wrong_answer_id",
                type="string",
                description="UUID of the wrong answer record to derive a diagnostic question from.",
                required=True,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        import uuid as uuid_mod

        from models.practice import PracticeProblem, WrongAnswer
        from services.practice.annotation import build_practice_problem

        try:
            wa_id_str = parameters.get("wrong_answer_id", "")
            try:
                wa_id = uuid_mod.UUID(wa_id_str)
            except (ValueError, AttributeError):
                return ToolResult(success=False, output="", error=f"Invalid wrong_answer_id: {wa_id_str}")

            result = await db.execute(
                select(WrongAnswer, PracticeProblem)
                .join(PracticeProblem, WrongAnswer.problem_id == PracticeProblem.id)
                .where(
                    WrongAnswer.id == wa_id,
                    WrongAnswer.user_id == ctx.user_id,
                )
            )
            row = result.one_or_none()
            if not row:
                return ToolResult(success=False, output="", error="Wrong answer not found.")

            wa, problem = row

            # Check for existing diagnostic (filter in DB to avoid loading all rows)
            existing_result = await db.execute(
                select(PracticeProblem)
                .where(
                    PracticeProblem.parent_problem_id == problem.id,
                    PracticeProblem.is_diagnostic == True,  # noqa: E712
                    PracticeProblem.problem_metadata["wrong_answer_id"].astext == str(wa.id),
                )
                .limit(1)
            )
            existing = existing_result.scalar_one_or_none()
            if existing:
                ctx.actions.append({"action": "data_updated", "value": "practice"})
                return ToolResult(
                    success=True,
                    output=f"Diagnostic already exists: {existing.question}",
                )

            # Build LLM prompt
            metadata_str = ""
            if problem.problem_metadata:
                meta = problem.problem_metadata
                parts = []
                if meta.get("core_concept"):
                    parts.append(f"Core concept: {meta['core_concept']}")
                if meta.get("potential_traps"):
                    parts.append(f"Known traps to remove: {', '.join(meta['potential_traps'])}")
                if parts:
                    metadata_str = "\nQuestion metadata:\n" + "\n".join(parts)

            ctx.emit_progress(self.name, "Generating diagnostic question...", step=1, total=2)

            from services.llm.router import get_llm_client

            client = get_llm_client()
            prompt = (
                f"You are a diagnostic question designer. A student got this question wrong.\n"
                f"Generate a SIMPLIFIED diagnostic version that:\n"
                f"1. Tests the EXACT SAME core concept\n"
                f"2. Removes all distractors, traps, and misleading wording\n"
                f"3. Uses simpler numbers/context\n\n"
                f"Original question: {problem.question}\n"
                f"Question type: {problem.question_type}\n"
                f"Correct answer: {wa.correct_answer}\n"
                f"Student's wrong answer: {wa.user_answer}\n"
                f"Error category: {wa.error_category or 'unknown'}\n"
                f"{metadata_str}\n\n"
                f'Return JSON only:\n'
                f'{{"question": "...", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}} or null, '
                f'"correct_answer": "...", "explanation": "...", '
                f'"simplifications_made": ["list"], "core_concept_preserved": "..."}}'
            )

            response, _ = await client.chat(
                "You design diagnostic questions. Output valid JSON only.",
                prompt,
            )

            try:
                derived = json.loads(response)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", response, re.DOTALL)
                derived = json.loads(match.group()) if match else {}

            if not derived.get("question"):
                derived["question"] = f"Diagnostic check: {problem.question}"
            if derived.get("options") is None and problem.options:
                derived["options"] = problem.options
            if not derived.get("correct_answer"):
                derived["correct_answer"] = wa.correct_answer or problem.correct_answer

            extra_metadata = {
                "simplifications_made": derived.get("simplifications_made", []),
                "core_concept_preserved": derived.get("core_concept_preserved", ""),
                "original_problem_id": str(problem.id),
                "wrong_answer_id": str(wa.id),
            }
            new_problem = build_practice_problem(
                course_id=problem.course_id,
                content_node_id=problem.content_node_id,
                title=(problem.problem_metadata or {}).get("core_concept", problem.question[:80] or "Diagnostic"),
                question={
                    "question_type": problem.question_type,
                    "question": derived.get("question", ""),
                    "options": derived.get("options"),
                    "correct_answer": derived.get("correct_answer"),
                    "explanation": derived.get("explanation", "Simplified diagnostic follow-up."),
                    "difficulty_layer": 1,
                    "problem_metadata": {
                        "core_concept": derived.get("core_concept_preserved", ""),
                        "bloom_level": "understand",
                        "potential_traps": [],
                        "layer_justification": "Simplified diagnostic variant.",
                        "skill_focus": "core concept check",
                        "source_section": (problem.problem_metadata or {}).get("source_section", "Diagnostic"),
                    },
                },
                order_index=problem.order_index,
                knowledge_points=wa.knowledge_points or problem.knowledge_points,
                source="derived",
                parent_problem_id=problem.id,
                is_diagnostic=True,
                difficulty_layer_default=1,
                extra_metadata=extra_metadata,
            )
            db.add(new_problem)
            await db.flush()

            ctx.emit_progress(self.name, "Done", step=2, total=2)
            ctx.actions.append({"action": "data_updated", "value": "practice"})

            return ToolResult(
                success=True,
                output=f"Created diagnostic question: {derived.get('question', '')[:100]}",
            )
        except Exception as e:
            await db.rollback()
            logger.error("derive_diagnostic tool failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))


# ── Registry Helper ──


def get_builtin_tools() -> list[Tool]:
    """Return all built-in education tools for registration."""
    return [
        LookupProgressTool(),
        SearchContentTool(),
        ListWrongAnswersTool(),
        GetMasteryReportTool(),
        GetCourseOutlineTool(),
        ListStudyGoalsTool(),
        ListRecentTasksTool(),
        ListAssignmentsTool(),
        RunCodeTool(),
        CheckPrerequisitesTool(),
        SuggestRelatedTopicsTool(),
        GetForgettingForecastTool(),
        # Write tools
        GenerateFlashcardsTool(),
        GenerateQuizTool(),
        GenerateNotesTool(),
        CreateStudyPlanTool(),
        DeriveDiagnosticTool(),
    ]
