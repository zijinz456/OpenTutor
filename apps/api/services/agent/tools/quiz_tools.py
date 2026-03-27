"""Quiz generation, diagnostic, and comprehension probing tools.

Tools:
- generate_quiz_tool (WRITE): Generate practice quiz questions from course materials.
- derive_diagnostic_tool (WRITE): Generate simplified follow-up from a wrong answer.
- record_comprehension_tool (WRITE): Record comprehension probe results and update mastery.
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


@tool(
    name="record_comprehension",
    description=(
        "Record the result of a comprehension probe. Call this after asking the student "
        "a transfer question, misconception probe, or Feynman explanation and evaluating "
        "their response. This updates the student's mastery tracking and FSRS schedule."
    ),
    category=ToolCategory.WRITE,
    params=[
        param("topic", "string", "The concept/topic being probed", required=True),
        param("understood", "boolean", "Whether the student demonstrated true understanding", required=True),
        param("probe_type", "string", "Type of probe: transfer | misconception | feynman", required=True),
        param("misconception_type", "string", "If understood=false: surface_memorization | confused_similar | missing_prerequisite | procedural_only | partial_understanding", required=False),
        param("notes", "string", "Brief notes on what the student got right or wrong", required=False),
    ],
)
async def record_comprehension_tool(parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
    """Record comprehension probe result and update mastery/FSRS."""
    from models.progress import LearningProgress
    from models.content import CourseContentTree

    topic = parameters.get("topic", "").strip()
    understood = parameters.get("understood", False)
    probe_type = parameters.get("probe_type", "transfer")
    misconception_type = parameters.get("misconception_type")
    notes = parameters.get("notes", "")

    if not topic:
        return ToolResult(success=False, output="", error="topic is required")

    try:
        # Find matching content node by title (fuzzy)
        from sqlalchemy import or_
        result = await db.execute(
            select(CourseContentTree).where(
                CourseContentTree.course_id == ctx.course_id,
                or_(
                    CourseContentTree.title.ilike(f"%{topic}%"),
                    CourseContentTree.content.ilike(f"%{topic}%"),
                ),
            ).limit(1)
        )
        content_node = result.scalar_one_or_none()
        node_id = content_node.id if content_node else None
        node_title = content_node.title if content_node else topic

        # Find or create LearningProgress entry
        progress_result = await db.execute(
            select(LearningProgress).where(
                LearningProgress.user_id == ctx.user_id,
                LearningProgress.course_id == ctx.course_id,
                LearningProgress.content_node_title == node_title,
            )
        )
        progress = progress_result.scalar_one_or_none()

        if not progress:
            progress = LearningProgress(
                user_id=ctx.user_id,
                course_id=ctx.course_id,
                content_node_id=node_id,
                content_node_title=node_title,
                mastery_score=0.0,
                quiz_attempts=0,
                quiz_correct=0,
                time_spent_minutes=0,
            )
            db.add(progress)

        # Update mastery based on comprehension probe result
        # Comprehension probes are weighted more heavily than quiz answers
        # because they test true understanding, not just recall
        probe_weight = {"transfer": 0.15, "misconception": 0.12, "feynman": 0.10}.get(probe_type, 0.10)

        if understood:
            # Boost mastery toward 1.0
            progress.mastery_score = min(1.0, progress.mastery_score + probe_weight)
            progress.quiz_attempts += 1
            progress.quiz_correct += 1
        else:
            # Reduce mastery — misconception detected
            penalty = probe_weight * 1.5  # Wrong comprehension is worse than wrong quiz
            progress.mastery_score = max(0.0, progress.mastery_score - penalty)
            progress.quiz_attempts += 1

            # Record gap type based on misconception
            if misconception_type:
                gap_map = {
                    "surface_memorization": "layer1_fail",
                    "confused_similar": "conceptual",
                    "missing_prerequisite": "prerequisite",
                    "procedural_only": "procedural",
                    "partial_understanding": "layer2_fail",
                }
                progress.gap_type = gap_map.get(misconception_type, "conceptual")

        # Update FSRS scheduling based on probe result
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        progress.last_activity_at = now

        if understood:
            # Good recall — extend review interval
            current_stability = float(progress.fsrs_stability or 1.0)
            progress.fsrs_stability = current_stability * 1.5
            progress.next_review_at = now + timedelta(days=current_stability * 1.5)
        else:
            # Failed probe — reset to short interval for re-review
            progress.fsrs_stability = 0.5
            progress.next_review_at = now + timedelta(hours=4)

        # Store probe metadata in the metadata field
        probe_record = {
            "type": probe_type,
            "understood": understood,
            "misconception_type": misconception_type,
            "notes": notes,
            "timestamp": now.isoformat(),
        }
        existing_probes = (progress.metadata_json or {}).get("comprehension_probes", [])
        existing_probes.append(probe_record)
        # Keep last 50 probes
        existing_probes = existing_probes[-50:]
        if progress.metadata_json is None:
            progress.metadata_json = {}
        progress.metadata_json["comprehension_probes"] = existing_probes

        await db.flush()

        if understood:
            return ToolResult(
                success=True,
                output=f"Comprehension confirmed for '{node_title}' ({probe_type} probe). "
                       f"Mastery: {progress.mastery_score:.0%}. Next review scheduled.",
            )
        else:
            return ToolResult(
                success=True,
                output=f"Misconception detected for '{node_title}': {misconception_type or 'unspecified'}. "
                       f"Mastery adjusted to {progress.mastery_score:.0%}. "
                       f"Re-review scheduled in 4 hours. Notes: {notes}",
            )

    except SQLAlchemyError as e:
        logger.exception("record_comprehension DB error: %s", e)
        return ToolResult(success=False, output="", error="Database error recording comprehension.")
    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
        from libs.exceptions import reraise_as_app_error
        reraise_as_app_error(e, f"record_comprehension failed: {e}")
