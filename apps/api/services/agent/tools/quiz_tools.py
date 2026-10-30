"""Quiz generation and diagnostic tools.

Tools:
- generate_quiz_tool (WRITE): Generate practice quiz questions from course materials.
- derive_diagnostic_tool (WRITE): Generate simplified follow-up from a wrong answer.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import ToolCategory, ToolResult, param, tool

logger = logging.getLogger(__name__)


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

        outcome = await extract_questions(content, title, ctx.course_id)
        problems = outcome.problems
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
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception("generate_quiz DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error saving quiz questions.")
    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
        await db.rollback()
        from libs.exceptions import reraise_as_app_error
        reraise_as_app_error(e, f"generate_quiz failed: {e}")


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
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception("derive_diagnostic DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error creating diagnostic question.")
    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
        await db.rollback()
        from libs.exceptions import reraise_as_app_error
        reraise_as_app_error(e, f"derive_diagnostic failed: {e}")
