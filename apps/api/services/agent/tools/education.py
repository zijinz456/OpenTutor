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
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolCategory, ToolResult, param, tool

logger = logging.getLogger(__name__)


# ── READ tools ──


@tool(
    name="lookup_progress",
    description=(
        "Look up the student's learning progress and mastery scores. "
        "Returns mastery levels, gap types, and study time for each topic."
    ),
    params=[param("topic", "string", "Optional topic name to filter by (partial match). Leave empty for all topics.", required=False)],
)
async def lookup_progress(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    from models.progress import LearningProgress
    from models.content import CourseContentTree

    try:
        stmt = (
            select(LearningProgress, CourseContentTree.title)
            .outerjoin(CourseContentTree, LearningProgress.content_node_id == CourseContentTree.id)
            .where(LearningProgress.user_id == ctx.user_id, LearningProgress.course_id == ctx.course_id)
        )
        result = await db.execute(stmt)
        rows = result.all()

        if not rows:
            return ToolResult(success=True, output="No learning progress data found for this student/course.")

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


@tool(
    name="search_content",
    description=(
        "Search the course materials for specific content. "
        "Use this when the initial context doesn't have enough information "
        "to answer the student's question."
    ),
    params=[param("query", "string", "Search query to find relevant course content.")],
)
async def search_content(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
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

        return ToolResult(success=True, output=f"Found {len(results)} relevant sections:\n\n" + "\n".join(lines))
    except Exception as e:
        logger.error("search_content failed: %s", e)
        return ToolResult(success=False, output="", error=str(e))


@tool(
    name="list_wrong_answers",
    description=(
        "List the student's wrong answers with error categories and diagnosis. "
        "Useful for review, error analysis, and identifying weak areas."
    ),
    params=[
        param("error_category", "string", "Filter by error type.", required=False,
              enum=["conceptual", "procedural", "computational", "reading", "careless"]),
        param("mastered", "boolean", "Filter by mastery status. false=still need review, true=already mastered.", required=False),
        param("limit", "integer", "Maximum number of results (default 5).", required=False, default=5),
    ],
)
async def list_wrong_answers(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    from models.ingestion import WrongAnswer

    try:
        stmt = select(WrongAnswer).where(
            WrongAnswer.user_id == ctx.user_id, WrongAnswer.course_id == ctx.course_id,
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

        return ToolResult(success=True, output=f"Wrong answers ({len(rows)} results):\n" + "\n".join(lines))
    except Exception as e:
        logger.error("list_wrong_answers failed: %s", e)
        return ToolResult(success=False, output="", error=str(e))


@tool(
    name="get_mastery_report",
    description=(
        "Generate a comprehensive learning report: overall mastery, "
        "weak areas, study time, quiz accuracy, and error patterns. "
        "No parameters needed — uses the current student and course."
    ),
)
async def get_mastery_report(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    from models.progress import LearningProgress
    from models.ingestion import StudySession, WrongAnswer

    try:
        progress_q = select(LearningProgress).where(
            LearningProgress.user_id == ctx.user_id, LearningProgress.course_id == ctx.course_id,
        )
        wrong_stats_q = select(
            WrongAnswer.error_category, func.count(WrongAnswer.id),
        ).where(
            WrongAnswer.user_id == ctx.user_id, WrongAnswer.course_id == ctx.course_id,
            WrongAnswer.mastered == False,  # noqa: E712
        ).group_by(WrongAnswer.error_category)

        session_q = select(
            func.count(StudySession.id), func.sum(StudySession.duration_minutes),
            func.sum(StudySession.problems_attempted), func.sum(StudySession.problems_correct),
        ).where(StudySession.user_id == ctx.user_id, StudySession.course_id == ctx.course_id)

        # Run sequentially — AsyncSession is NOT safe for concurrent use
        progress_res = await db.execute(progress_q)
        wrong_res = await db.execute(wrong_stats_q)
        session_res = await db.execute(session_q)

        progress_rows = progress_res.scalars().all()
        wrong_cats = wrong_res.all()
        session_stats = session_res.one_or_none()

        parts = ["## Learning Report\n"]
        if progress_rows:
            avg_mastery = sum(r.mastery_score or 0 for r in progress_rows) / len(progress_rows)
            mastered_count = sum(1 for r in progress_rows if r.status == "mastered")
            gap_counts: dict[str, int] = {}
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

        if wrong_cats:
            parts.append("\n**Unmastered errors by category**:")
            for cat, count in wrong_cats:
                parts.append(f"  - {cat or 'unclassified'}: {count}")

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


@tool(
    name="run_code",
    description=(
        "Execute Python code safely and return the output. "
        "Supports math, collections, statistics, and other standard library modules. "
        "Blocks dangerous operations (file I/O, network, system calls)."
    ),
    category=ToolCategory.COMPUTE,
    params=[param("code", "string", "Python code to execute.")],
)
async def run_code(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    from services.agent.code_execution import CodeExecutionAgent

    code = parameters.get("code", "").strip()
    if not code:
        return ToolResult(success=False, output="", error="No code provided.")

    agent = CodeExecutionAgent()
    safe, reason = agent._validate_code(code)
    if not safe:
        return ToolResult(success=False, output="", error=f"Unsafe code: {reason}")

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


@tool(
    name="check_prerequisites",
    description=(
        "Check if the student has mastered the prerequisites for a given topic. "
        "Returns which prerequisites are met and which have gaps."
    ),
    params=[param("topic", "string", "The topic to check prerequisites for.")],
)
async def check_prerequisites(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    from models.content import CourseContentTree, KnowledgePoint
    from models.progress import LearningProgress

    topic = parameters.get("topic", "").strip()
    if not topic:
        return ToolResult(success=False, output="", error="No topic provided.")

    try:
        kp_result = await db.execute(
            select(KnowledgePoint)
            .where(KnowledgePoint.course_id == ctx.course_id, KnowledgePoint.name.ilike(f"%{topic}%"))
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
            for dep_id in deps:
                dep_result = await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == dep_id))
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

        return ToolResult(success=True, output="Prerequisites check:\n" + "\n".join(lines))
    except Exception as e:
        logger.error("check_prerequisites failed: %s", e)
        return ToolResult(success=False, output="", error=str(e))


@tool(
    name="suggest_related_topics",
    description=(
        "Find topics related to a given concept based on the course knowledge graph. "
        "Useful for expanding learning or finding connections."
    ),
    params=[param("topic", "string", "The topic to find related concepts for.")],
)
async def suggest_related_topics(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    from models.content import KnowledgePoint

    topic = parameters.get("topic", "").strip()
    if not topic:
        return ToolResult(success=False, output="", error="No topic provided.")

    try:
        result = await db.execute(
            select(KnowledgePoint)
            .where(KnowledgePoint.course_id == ctx.course_id, KnowledgePoint.name.ilike(f"%{topic}%"))
            .limit(3)
        )
        kps = result.scalars().all()

        if not kps:
            return ToolResult(success=True, output=f"No knowledge points found matching '{topic}'.")

        all_related_ids = set()
        source_ids = {kp.id for kp in kps}
        for kp in kps:
            if kp.dependencies:
                all_related_ids.update(kp.dependencies)

        # Single query to find reverse dependents (downstream) — avoids N+1
        all_course_kps = await db.execute(
            select(KnowledgePoint).where(KnowledgePoint.course_id == ctx.course_id)
        )
        for other in all_course_kps.scalars().all():
            if other.dependencies and source_ids & set(other.dependencies):
                all_related_ids.add(other.id)

        all_related_ids -= source_ids

        lines = []
        if all_related_ids:
            related_result = await db.execute(
                select(KnowledgePoint).where(KnowledgePoint.id.in_(list(all_related_ids)[:10]))
            )
            for related in related_result.scalars().all():
                lines.append(f"- {related.name}")

        if not lines:
            return ToolResult(success=True, output=f"No related topics found for '{topic}' in the knowledge graph.")

        return ToolResult(success=True, output=f"Related topics for '{topic}':\n" + "\n".join(lines))
    except Exception as e:
        logger.error("suggest_related_topics failed: %s", e)
        return ToolResult(success=False, output="", error=str(e))


@tool(
    name="get_forgetting_forecast",
    description=(
        "Predict which topics the student is about to forget based on FSRS spaced repetition data. "
        "Returns topics sorted by urgency (most at-risk first)."
    ),
)
async def get_forgetting_forecast(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
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


@tool(
    name="get_course_outline",
    description=(
        "Return the top-level course outline from the course content tree. "
        "Useful for planning, curriculum analysis, and grounding answers in structure."
    ),
)
async def get_course_outline(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
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


@tool(
    name="list_study_goals",
    description="List the student's study goals for the current course.",
    params=[param("status", "string", "Optional goal status filter.", required=False, enum=["active", "paused", "completed"])],
)
async def list_study_goals(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    from models.study_goal import StudyGoal

    try:
        stmt = (
            select(StudyGoal)
            .where(StudyGoal.user_id == ctx.user_id, StudyGoal.course_id == ctx.course_id)
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


@tool(
    name="list_recent_tasks",
    description="List recent durable agent tasks, including approvals and failures.",
    params=[param("limit", "integer", "Maximum number of tasks to return.", required=False, default=5)],
)
async def list_recent_tasks(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    from models.agent_task import AgentTask

    try:
        limit = min(int(parameters.get("limit", 5)), 10)
        result = await db.execute(
            select(AgentTask)
            .where(AgentTask.user_id == ctx.user_id, AgentTask.course_id == ctx.course_id)
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


@tool(
    name="list_assignments",
    description="List assignments, quizzes, or exams associated with the course.",
    params=[
        param("limit", "integer", "Maximum number of assignments to return.", required=False, default=10),
        param("include_completed", "boolean", "Whether to include completed assignments.", required=False, default=False),
    ],
)
async def list_assignments(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
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
            f"- {a.title}: type={a.assignment_type or 'general'}, status={a.status}, due={a.due_date or 'unspecified'}"
            for a in assignments
        ]
        return ToolResult(success=True, output="Assignments:\n" + "\n".join(lines))
    except Exception as e:
        logger.error("list_assignments failed: %s", e)
        return ToolResult(success=False, output="", error=str(e))


# ── WRITE tools ──


@tool(
    name="generate_flashcards",
    description=(
        "Generate spaced-repetition flashcards from course materials. "
        "Creates cards with question/answer pairs and saves them for review. "
        "Use when the student asks for flashcards or study cards."
    ),
    category=ToolCategory.WRITE,
    params=[param("count", "integer", "Number of flashcards to generate (1-20). Default 5.", required=False, default=5)],
)
async def generate_flashcards_tool(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    try:
        count = min(max(int(parameters.get("count", 5)), 1), 20)
        ctx.emit_progress("generate_flashcards", "Analysing course content...", step=1, total=3)

        from services.spaced_repetition.flashcards import generate_flashcards

        cards = await generate_flashcards(db, ctx.course_id, count=count)
        if not cards:
            return ToolResult(success=True, output="No flashcards could be generated. The course may lack sufficient content.")

        ctx.emit_progress("generate_flashcards", f"Saving {len(cards)} flashcards...", step=2, total=3)

        from services.generated_assets import save_generated_asset

        await save_generated_asset(
            db, user_id=ctx.user_id, course_id=ctx.course_id,
            asset_type="flashcards", title="AI-Generated Flashcards",
            content={"cards": cards}, metadata={"count": len(cards)},
        )
        await db.flush()

        ctx.emit_progress("generate_flashcards", "Done", step=3, total=3)
        ctx.actions.append({"action": "data_updated", "value": "practice"})

        summary_lines = [f"- Q: {c.get('front', '')[:60]}..." for c in cards[:5]]
        return ToolResult(success=True, output=f"Generated {len(cards)} flashcards:\n" + "\n".join(summary_lines))
    except Exception as e:
        await db.rollback()
        logger.error("generate_flashcards tool failed: %s", e)
        return ToolResult(success=False, output="", error=str(e))


@tool(
    name="generate_quiz",
    description=(
        "Generate practice quiz questions from course materials. "
        "Creates multiple-choice, true/false, or short-answer questions and saves them. "
        "Use when the student asks for quiz questions, practice problems, or test prep."
    ),
    category=ToolCategory.WRITE,
    params=[
        param("topic", "string", "Optional topic to focus questions on. Leave empty for general questions.", required=False),
        param("count", "integer", "Number of questions to generate (1-10). Default 3.", required=False, default=3),
    ],
)
async def generate_quiz_tool(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    try:
        topic = parameters.get("topic", "").strip()
        count = min(max(int(parameters.get("count", 3)), 1), 10)

        ctx.emit_progress("generate_quiz", "Searching course content...", step=1, total=3)

        from services.search.hybrid import hybrid_search

        query = topic or "key concepts"
        results = await hybrid_search(db, ctx.course_id, query, limit=3)
        if not results:
            return ToolResult(success=True, output="No course content found to generate questions from.")

        content = "\n\n".join(r.get("content", "")[:2000] for r in results)
        title = topic or results[0].get("title", "Course Content")

        ctx.emit_progress("generate_quiz", "Generating questions...", step=2, total=3)

        from services.parser.quiz import extract_questions

        problems = await extract_questions(content, title, ctx.course_id)
        if not problems:
            return ToolResult(success=True, output="No questions could be extracted from the content.")

        problems = problems[:count]
        for p in problems:
            db.add(p)
        await db.flush()

        ctx.emit_progress("generate_quiz", "Done", step=3, total=3)
        ctx.actions.append({"action": "data_updated", "value": "practice"})

        summary_lines = [f"- [{p.question_type}] {(p.question or '')[:60]}..." for p in problems]
        return ToolResult(success=True, output=f"Generated {len(problems)} quiz questions:\n" + "\n".join(summary_lines))
    except Exception as e:
        await db.rollback()
        logger.error("generate_quiz tool failed: %s", e)
        return ToolResult(success=False, output="", error=str(e))


@tool(
    name="generate_notes",
    description=(
        "Generate structured study notes from course materials in various formats. "
        "Supports bullet points, tables, mind maps, step-by-step, and summaries. "
        "Use when the student asks for notes, summaries, or study guides."
    ),
    category=ToolCategory.WRITE,
    params=[
        param("topic", "string", "Topic to generate notes about."),
        param("format", "string", "Note format: bullet_point, table, mind_map, step_by_step, or summary.",
              required=False, default="bullet_point", enum=["bullet_point", "table", "mind_map", "step_by_step", "summary"]),
    ],
)
async def generate_notes_tool(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    try:
        topic = parameters.get("topic", "").strip()
        if not topic:
            return ToolResult(success=False, output="", error="Topic is required.")

        note_format = parameters.get("format", "bullet_point")
        ctx.emit_progress("generate_notes", f"Searching content for '{topic}'...", step=1, total=3)

        from services.search.hybrid import hybrid_search

        results = await hybrid_search(db, ctx.course_id, topic, limit=5)
        if not results:
            return ToolResult(success=True, output=f"No course content found for topic '{topic}'.")

        content = "\n\n".join(r.get("content", "")[:2000] for r in results)
        ctx.emit_progress("generate_notes", f"Generating {note_format} notes...", step=2, total=3)

        from services.parser.notes import restructure_notes

        notes_md = await restructure_notes(content, topic, note_format=note_format)
        if not notes_md or not notes_md.strip():
            return ToolResult(success=True, output="Could not generate notes from the available content.")

        from services.generated_assets import save_generated_asset

        await save_generated_asset(
            db, user_id=ctx.user_id, course_id=ctx.course_id,
            asset_type="notes", title=f"Notes: {topic}",
            content={"markdown": notes_md, "format": note_format},
            metadata={"topic": topic, "format": note_format},
        )
        await db.flush()

        ctx.emit_progress("generate_notes", "Done", step=3, total=3)
        ctx.actions.append({"action": "data_updated", "value": "notes"})

        preview = notes_md[:300] + ("..." if len(notes_md) > 300 else "")
        return ToolResult(success=True, output=f"Generated {note_format} notes for '{topic}':\n\n{preview}")
    except Exception as e:
        await db.rollback()
        logger.error("generate_notes tool failed: %s", e)
        return ToolResult(success=False, output="", error=str(e))


@tool(
    name="create_study_plan",
    description=(
        "Create a personalized study plan or exam preparation plan. "
        "Analyzes the student's progress and generates a day-by-day schedule. "
        "Use when the student asks for a study plan, exam prep, or revision schedule."
    ),
    category=ToolCategory.WRITE,
    params=[
        param("exam_topic", "string", "Optional specific exam topic to focus on.", required=False),
        param("days_until_exam", "integer", "Number of days until the exam (1-90). Default 7.", required=False, default=7),
    ],
)
async def create_study_plan_tool(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    try:
        exam_topic = parameters.get("exam_topic", "").strip() or None
        days = min(max(int(parameters.get("days_until_exam", 7)), 1), 90)

        ctx.emit_progress("create_study_plan", "Assessing readiness...", step=1, total=3)

        from services.workflow.exam_prep import run_exam_prep

        result = await run_exam_prep(
            db, ctx.user_id, ctx.course_id, exam_topic=exam_topic, days_until_exam=days,
        )

        plan_md = result.get("plan", "")
        if not plan_md:
            return ToolResult(success=True, output="Could not generate a study plan.")

        ctx.emit_progress("create_study_plan", "Saving study plan...", step=2, total=3)

        from services.generated_assets import save_generated_asset

        await save_generated_asset(
            db, user_id=ctx.user_id, course_id=ctx.course_id,
            asset_type="study_plan",
            title=f"{'Exam Prep' if exam_topic else 'Study'} Plan ({days} days)",
            content={"markdown": plan_md, "readiness": result.get("readiness")},
            metadata={"days_until_exam": days, "exam_topic": exam_topic, "topics_count": result.get("topics_count", 0)},
        )
        await db.flush()

        ctx.emit_progress("create_study_plan", "Done", step=3, total=3)
        ctx.actions.append({"action": "data_updated", "value": "plan"})

        preview = plan_md[:400] + ("..." if len(plan_md) > 400 else "")
        return ToolResult(success=True, output=f"Created {days}-day study plan:\n\n{preview}")
    except Exception as e:
        await db.rollback()
        logger.error("create_study_plan tool failed: %s", e)
        return ToolResult(success=False, output="", error=str(e))


@tool(
    name="derive_diagnostic",
    description=(
        "Generate a simplified diagnostic follow-up question based on a student's wrong answer. "
        "The diagnostic version removes traps/distractors while preserving the core concept, "
        "helping determine if the error was due to a concept gap or carelessness. "
        "Use when reviewing wrong answers and wanting to create targeted follow-up practice."
    ),
    category=ToolCategory.WRITE,
    params=[param("wrong_answer_id", "string", "UUID of the wrong answer record to derive a diagnostic question from.")],
)
async def derive_diagnostic_tool(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    import uuid as uuid_mod

    from models.ingestion import WrongAnswer
    from models.practice import PracticeProblem
    from services.diagnosis.derive import derive_diagnostic

    try:
        wa_id_str = parameters.get("wrong_answer_id", "")
        try:
            wa_id = uuid_mod.UUID(wa_id_str)
        except (ValueError, AttributeError):
            return ToolResult(success=False, output="", error=f"Invalid wrong_answer_id: {wa_id_str}")

        result = await db.execute(
            select(WrongAnswer, PracticeProblem)
            .join(PracticeProblem, WrongAnswer.problem_id == PracticeProblem.id)
            .where(WrongAnswer.id == wa_id, WrongAnswer.user_id == ctx.user_id)
        )
        row = result.one_or_none()
        if not row:
            return ToolResult(success=False, output="", error="Wrong answer not found.")

        wa, problem = row

        # Check for existing diagnostic
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
            return ToolResult(success=True, output=f"Diagnostic already exists: {existing.question}")

        ctx.emit_progress("derive_diagnostic", "Generating diagnostic question...", step=1, total=2)

        new_problem = await derive_diagnostic(db, wa, problem)
        await db.flush()

        ctx.emit_progress("derive_diagnostic", "Done", step=2, total=2)
        ctx.actions.append({"action": "data_updated", "value": "practice"})

        return ToolResult(success=True, output=f"Created diagnostic question: {new_problem.question[:100]}")
    except Exception as e:
        await db.rollback()
        logger.error("derive_diagnostic tool failed: %s", e)
        return ToolResult(success=False, output="", error=str(e))


# ── Registry Helper ──


def get_builtin_tools() -> list[Tool]:
    """Return all built-in education tools for registration."""
    return [
        lookup_progress, search_content, list_wrong_answers,
        get_mastery_report, get_course_outline, list_study_goals,
        list_recent_tasks, list_assignments, run_code,
        check_prerequisites, suggest_related_topics, get_forgetting_forecast,
        # Write tools
        generate_flashcards_tool, generate_quiz_tool, generate_notes_tool,
        create_study_plan_tool, derive_diagnostic_tool,
    ]
