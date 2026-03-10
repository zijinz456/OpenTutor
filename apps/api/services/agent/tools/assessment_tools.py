"""Assessment and listing tools for the ReAct agent loop.

Includes READ tools for listing/querying and WRITE tools for workspace layout:
- list_wrong_answers: List student's wrong answers with error categories.
- list_study_goals: List study goals for the current course.
- list_recent_tasks: List recent durable agent tasks.
- list_assignments: List assignments, quizzes, or exams.
- sync_deadlines_to_calendar_tool: Export deadlines as .ics calendar file.
- update_workspace_layout: Update workspace layout using block actions.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import ToolCategory, ToolResult, param, tool

logger = logging.getLogger(__name__)


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
    except SQLAlchemyError as e:
        logger.exception("list_wrong_answers DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error while listing wrong answers.")
    except (ValueError, KeyError, TypeError, RuntimeError) as e:
        logger.exception("list_wrong_answers failed: %s", e)
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
    except SQLAlchemyError as e:
        logger.exception("list_study_goals DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error listing study goals.")
    except (ValueError, KeyError, TypeError, RuntimeError) as e:
        logger.exception("list_study_goals failed: %s", e)
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
    except SQLAlchemyError as e:
        logger.exception("list_recent_tasks DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error listing recent tasks.")
    except (ValueError, KeyError, TypeError, RuntimeError) as e:
        logger.exception("list_recent_tasks failed: %s", e)
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

        lines = []
        for a in assignments:
            meta = a.metadata_json or {}
            source = meta.get("extraction_source", "manual")
            confidence = meta.get("extraction_confidence")
            line = f"- {a.title}: type={a.assignment_type or 'general'}, status={a.status}, due={a.due_date or 'unspecified'}"
            if source != "manual":
                line += f" [auto-extracted, source={source}"
                if confidence is not None:
                    line += f", confidence={confidence:.0%}"
                line += "]"
            lines.append(line)
        return ToolResult(success=True, output="Assignments:\n" + "\n".join(lines))
    except SQLAlchemyError as e:
        logger.exception("list_assignments DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error listing assignments.")
    except (ValueError, KeyError, TypeError, RuntimeError) as e:
        logger.exception("list_assignments failed: %s", e)
        return ToolResult(success=False, output="", error=str(e))


@tool(
    name="sync_deadlines_to_calendar",
    description="Export assignment deadlines as .ics calendar file.",
    category=ToolCategory.WRITE,
    params=[],
)
async def sync_deadlines_to_calendar_tool(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    from models.ingestion import Assignment

    try:
        result = await db.execute(
            select(Assignment)
            .where(Assignment.course_id == ctx.course_id, Assignment.due_date.isnot(None), Assignment.status == "active")
        )
        assignments = result.scalars().all()
        if not assignments:
            return ToolResult(success=True, output="No assignments with deadlines to export.")

        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//OpenTutor//EN"]
        for a in assignments:
            lines.extend([
                "BEGIN:VEVENT",
                f"SUMMARY:{a.title}",
                f"DTSTART;VALUE=DATE:{a.due_date.strftime('%Y%m%d')}",
                f"DESCRIPTION:{a.title}",
                "END:VEVENT",
            ])
        lines.append("END:VCALENDAR")
        return ToolResult(success=True, output=f"Generated .ics calendar for {len(assignments)} deadline(s).")
    except SQLAlchemyError as e:
        logger.exception("sync_deadlines_to_calendar DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error exporting deadlines.")
    except (ValueError, KeyError, TypeError, RuntimeError) as e:
        logger.exception("sync_deadlines_to_calendar failed: %s", e)
        return ToolResult(success=False, output="", error=str(e))


@tool(
    name="update_workspace_layout",
    description=(
        "Update the user's workspace layout using PRD-aligned block actions. "
        "Legacy preset/toggle inputs are mapped to block actions such as "
        "apply_template, add_block, and remove_block."
    ),
    category=ToolCategory.WRITE,
    params=[
        param("preset", "string", "Layout preset to apply.", required=False,
              enum=["daily_study", "exam_prep", "assignment", "minimal"]),
        param("toggle_section", "string", "Section to toggle visibility.", required=False,
              enum=["notes", "practice", "analytics", "plan"]),
        param("visible", "boolean", "Whether the section should be visible (used with toggle_section).", required=False),
    ],
)
async def update_workspace_layout(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    preset = parameters.get("preset")
    section = parameters.get("toggle_section")
    visible = parameters.get("visible", True)

    if preset:
        preset_to_template = {
            "daily_study": "stem_student",
            "exam_prep": "quick_reviewer",
            "assignment": "stem_student",
            "minimal": "blank_canvas",
        }
        template_id = preset_to_template.get(preset, preset)
        ctx.actions.append({"action": "apply_template", "value": template_id})
        return ToolResult(success=True, output=f"Applied template: {template_id}")
    elif section:
        section_to_block = {
            "notes": "notes",
            "practice": "quiz",
            "analytics": "progress",
            "plan": "plan",
        }
        default_size = {
            "notes": "large",
            "quiz": "large",
            "progress": "small",
            "plan": "medium",
        }
        block_type = section_to_block.get(section)
        if not block_type:
            return ToolResult(success=False, output="", error=f"Unsupported section: {section}")

        if visible:
            ctx.actions.append({"action": "add_block", "value": f"{block_type}:{default_size[block_type]}"})
            return ToolResult(success=True, output=f"Added block for section: {section}")

        ctx.actions.append({"action": "remove_block", "value": block_type})
        return ToolResult(success=True, output=f"Removed block for section: {section}")
    else:
        return ToolResult(success=False, output="", error="Provide either 'preset' or 'toggle_section' parameter.")
