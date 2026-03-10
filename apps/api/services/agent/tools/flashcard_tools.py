"""Content generation tools: flashcards, notes, and study plans.

Tools:
- generate_flashcards_tool (WRITE): Generate spaced-repetition flashcards.
- generate_notes_tool (WRITE): Generate structured study notes.
- create_study_plan_tool (WRITE): Create a personalized study/exam plan.
"""

import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import ToolCategory, ToolResult, param, tool

logger = logging.getLogger(__name__)


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
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception("generate_flashcards DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error saving flashcards.")
    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
        await db.rollback()
        from libs.exceptions import reraise_as_app_error
        reraise_as_app_error(e, f"generate_flashcards failed: {e}")


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
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception("generate_notes DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error saving notes.")
    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
        await db.rollback()
        from libs.exceptions import reraise_as_app_error
        reraise_as_app_error(e, f"generate_notes failed: {e}")


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

        # exam_prep workflow module removed — return graceful message
        logger.warning("exam_prep workflow module removed; create_study_plan returning no-op")
        plan_md = ""
        result = {}
        if not plan_md:
            return ToolResult(success=True, output="Study plan generation is currently unavailable (workflow module removed).")

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
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception("create_study_plan DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error saving study plan.")
    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
        await db.rollback()
        from libs.exceptions import ToolExecutionError
        logger.exception("create_study_plan failed: %s", e)
        raise ToolExecutionError(f"create_study_plan failed: {e}") from e
