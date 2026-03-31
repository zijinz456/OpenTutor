"""Task dispatch — routes task_type to the appropriate handler."""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session
from services.activity.engine_helpers import _normalize_uuid
from services.activity.task_types import JsonObject

logger = logging.getLogger(__name__)


async def dispatch_task(
    *,
    task_id: uuid.UUID,
    task_type: str,
    user_id: uuid.UUID,
    payload: JsonObject,
) -> tuple[JsonObject, str | None]:
    """Route a task to the correct handler based on task_type."""
    from services.activity.engine_multistep import _run_multi_step_plan

    async with async_session() as db:
        llm_task_labels = {
            "semester_init": "Semester initialization",
            "weekly_prep": "Weekly prep",
            "assignment_analysis": "Assignment analysis",
            "wrong_answer_review": "Wrong-answer review",
            "exam_prep": "Exam prep",
            "generate_quiz": "Quiz generation",
            "create_flashcard": "Flashcard generation",
            "create_flashcards": "Flashcard generation",
            "agent_subtask": "Agent task execution",
        }
        if task_type in llm_task_labels:
            from services.llm.readiness import ensure_llm_ready
            await ensure_llm_ready(llm_task_labels[task_type])

        if task_type == "weekly_prep":
            logger.warning("weekly_prep workflow module removed; skipping task")
            return {"skipped": True, "reason": "weekly_prep workflow removed"}, "Weekly prep workflow unavailable."

        if task_type == "exam_prep":
            logger.warning("exam_prep workflow module removed; skipping task")
            return {"skipped": True, "reason": "exam_prep workflow removed"}, "Exam prep workflow unavailable."

        if task_type == "wrong_answer_review":
            logger.warning("wrong_answer_review workflow module removed; skipping task")
            return {"skipped": True, "reason": "wrong_answer_review workflow removed"}, "Wrong-answer review workflow unavailable."

        if task_type == "assignment_analysis":
            logger.warning("assignment_analysis workflow module removed; skipping task")
            return {"skipped": True, "reason": "assignment_analysis workflow removed"}, "Assignment analysis workflow unavailable."

        if task_type == "generate_quiz":
            return await _dispatch_generate_quiz(db, user_id, payload)

        if task_type in {"create_flashcard", "create_flashcards"}:
            return await _dispatch_create_flashcards(db, user_id, payload)

        if task_type == "multi_step":
            return await _run_multi_step_plan(db, task_id, user_id, payload, async_session)

        if task_type == "chat_post_process":
            from services.agent.background_runtime import execute_post_process_task
            return await execute_post_process_task(payload, async_session)

        if task_type == "code_execution":
            return await _dispatch_code_execution(payload)

        if task_type == "memory_consolidation":
            from services.agent.memory_agent import run_full_consolidation
            result = await run_full_consolidation(db, user_id)
            return result, (
                f"Consolidated: deduped={result.get('deduped', 0)}, "
                f"decayed={result.get('decayed', 0)}, "
                f"categorized={result.get('categorized', 0)}"
            )

        if task_type == "agent_subtask":
            return await _dispatch_agent_subtask(db, user_id, payload)

        if task_type == "review_session":
            from services.agent.agenda_tasks import run_review_session
            result = await run_review_session(db, user_id, payload)
            return result, (result.get("summary", "") or "Review session completed.")[:300]

        if task_type == "reentry_session":
            from services.agent.agenda_tasks import run_reentry_session
            result = await run_reentry_session(db, user_id, payload)
            return result, (result.get("summary", "") or "Re-entry session prepared.")[:300]

        if task_type == "guided_session":
            from services.agent.guided_session import prepare_guided_session
            payload["task_id"] = str(task_id)
            result = await prepare_guided_session(db, user_id, payload)
            return result, (result.get("summary", "") or "Guided session prepared.")[:300]

        raise ValueError(f"Unsupported task_type: {task_type}")


async def _dispatch_generate_quiz(
    db: AsyncSession, user_id: uuid.UUID, payload: JsonObject,
) -> tuple[JsonObject, str | None]:
    from services.course_access import get_course_or_404
    from services.parser.quiz import extract_questions
    from services.search.hybrid import hybrid_search

    course_id = _normalize_uuid(payload.get("course_id"))
    if not course_id:
        raise ValueError("generate_quiz requires course_id")

    query = str(payload.get("topic") or payload.get("description") or "key concepts").strip()
    count = min(max(int(payload.get("count") or 3), 1), 10)
    await get_course_or_404(db, course_id, user_id=user_id)
    results = await hybrid_search(db, course_id, query or "key concepts", limit=3)
    if not results:
        return {"problem_ids": [], "count": 0, "query": query}, "No course content found to generate questions from."

    content = "\n\n".join(str(item.get("content", ""))[:2000] for item in results)
    title = str(payload.get("title") or payload.get("description") or results[0].get("title") or "Course Content")
    problems = await extract_questions(content, title, course_id)
    persisted = problems[:count]
    for problem in persisted:
        db.add(problem)
    await db.commit()
    return {
        "problem_ids": [str(problem.id) for problem in persisted],
        "count": len(persisted),
        "query": query,
    }, f"Generated {len(persisted)} quiz question(s)."


async def _dispatch_create_flashcards(
    db: AsyncSession, user_id: uuid.UUID, payload: JsonObject,
) -> tuple[JsonObject, str | None]:
    from services.course_access import get_course_or_404
    from services.generated_assets import save_generated_asset
    from services.spaced_repetition.flashcards import generate_flashcards

    course_id = _normalize_uuid(payload.get("course_id"))
    if not course_id:
        raise ValueError("create_flashcard requires course_id")

    content_node_id = _normalize_uuid(payload.get("content_node_id"))
    count = min(max(int(payload.get("count") or 5), 1), 20)
    course = await get_course_or_404(db, course_id, user_id=user_id)
    cards = await generate_flashcards(db, course_id, content_node_id, count)
    batch = None
    if cards:
        batch = await save_generated_asset(
            db, user_id=user_id, course_id=course_id,
            asset_type="flashcards",
            title=str(payload.get("title") or course.name),
            content={"cards": cards},
            metadata={"count": len(cards), "source": "agent_task"},
        )
    await db.commit()
    return {
        "cards": cards,
        "count": len(cards),
        "batch_id": str(batch["batch_id"]) if batch else None,
    }, f"Generated {len(cards)} flashcard(s)."


async def _dispatch_code_execution(payload: JsonObject) -> tuple[JsonObject, str | None]:
    from services.agent.code_execution import CodeExecutionAgent

    code = str(payload.get("code") or "")
    if not code.strip():
        raise ValueError("code_execution requires non-empty code")
    agent = CodeExecutionAgent()
    safe, reason = agent._validate_code(code)
    if not safe:
        raise ValueError(reason)
    result = await asyncio.to_thread(agent._execute_safe, code)
    if not result.get("success"):
        raise ValueError(result.get("error") or "Code execution failed")
    return result, f"Executed code in {result.get('backend', 'unknown')} sandbox"


async def _dispatch_agent_subtask(
    db: AsyncSession, user_id: uuid.UUID, payload: JsonObject,
) -> tuple[JsonObject, str | None]:
    agent_name = str(payload.get("agent_name", "teaching"))
    message = str(payload.get("message", ""))
    if not message.strip():
        raise ValueError("agent_subtask requires a non-empty message")

    from services.agent.registry import get_agent, build_agent_context
    agent = get_agent(agent_name)
    if not agent:
        raise ValueError(f"Unknown agent: {agent_name}")

    ctx = build_agent_context(
        user_id=user_id,
        course_id=_normalize_uuid(payload.get("course_id")),
        message=message,
        intent_type=payload.get("intent_type", "general"),
    )
    ctx = await agent.run(ctx, db)
    return {
        "agent": agent_name,
        "response": ctx.response or "",
    }, (ctx.response or "Agent subtask completed.")[:300]
