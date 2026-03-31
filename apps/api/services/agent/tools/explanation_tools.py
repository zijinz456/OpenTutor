"""Read-only lookup and analysis tools for the ReAct agent loop.

These tools have no side effects (ToolCategory.READ by default):
- lookup_progress: Look up student learning progress and mastery scores.
- search_content: Search course materials for specific content.
- get_mastery_report: Generate a comprehensive learning report.
- get_course_outline: Return the top-level course outline.
- get_forgetting_forecast: Predict which topics the student is about to forget.
- run_code: Execute Python code safely (ToolCategory.COMPUTE).
"""

import asyncio
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import ToolCategory, ToolResult, param, tool

logger = logging.getLogger(__name__)


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
    except SQLAlchemyError as e:
        logger.exception("lookup_progress DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error while looking up progress.")
    except (ValueError, KeyError, TypeError, RuntimeError) as e:
        logger.exception("lookup_progress failed: %s", e)
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
    except SQLAlchemyError as e:
        logger.exception("search_content DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error during search.")
    except (ValueError, KeyError, TypeError, RuntimeError) as e:
        logger.exception("search_content failed: %s", e)
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
    except SQLAlchemyError as e:
        logger.exception("get_mastery_report DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error generating mastery report.")
    except (ValueError, KeyError, TypeError, RuntimeError) as e:
        logger.exception("get_mastery_report failed: %s", e)
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
    except ImportError as e:
        logger.warning("get_forgetting_forecast unavailable (missing module): %s", e)
        return ToolResult(success=False, output="", error="Forgetting forecast module not available.")
    except SQLAlchemyError as e:
        logger.exception("get_forgetting_forecast DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error generating forecast.")
    except (ValueError, KeyError, TypeError, RuntimeError) as e:
        logger.exception("get_forgetting_forecast failed: %s", e)
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

        # Build id→title map for parent lookup
        id_to_title = {str(n.id): n.title for n in nodes}
        lines = []
        for node in nodes:
            if node.level > 2:
                continue
            indent = "  " * node.level
            title = node.title
            # Prefix child titles with parent name to avoid ambiguous "Slide 1" duplicates
            if node.level > 0 and node.parent_id and str(node.parent_id) in id_to_title:
                parent_title = id_to_title[str(node.parent_id)]
                title = f"{parent_title} > {title}"
            lines.append(f"{indent}- {title}")

        return ToolResult(success=True, output="Course outline:\n" + "\n".join(lines[:40]))
    except SQLAlchemyError as e:
        logger.exception("get_course_outline DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error fetching course outline.")
    except (ValueError, KeyError, TypeError, RuntimeError) as e:
        logger.exception("get_course_outline failed: %s", e)
        return ToolResult(success=False, output="", error=str(e))
