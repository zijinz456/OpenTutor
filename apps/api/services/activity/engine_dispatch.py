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


DispatchResult = tuple[JsonObject, str | None]

# Task types whose handler calls the LLM, with the readiness label shown to users.
_LLM_TASK_LABELS = {
    "generate_quiz": "Quiz generation",
    "create_flashcard": "Flashcard generation",
    "create_flashcards": "Flashcard generation",
}


async def _dispatch_multi_step(db, task_id, user_id, payload) -> DispatchResult:
    from services.activity.engine_multistep import _run_multi_step_plan
    return await _run_multi_step_plan(db, task_id, user_id, payload, async_session)


async def _dispatch_chat_post_process(db, task_id, user_id, payload) -> DispatchResult:
    from services.agent.background_runtime import execute_post_process_task
    return await execute_post_process_task(payload, async_session)


async def _dispatch_memory_consolidation(db, task_id, user_id, payload) -> DispatchResult:
    from services.agent.memory_agent import run_full_consolidation
    result = await run_full_consolidation(db, user_id)
    return result, (
        f"Consolidated: deduped={result.get('deduped', 0)}, "
        f"decayed={result.get('decayed', 0)}, "
        f"categorized={result.get('categorized', 0)}"
    )


async def _dispatch_review_session(db, task_id, user_id, payload) -> DispatchResult:
    from services.agent.agenda_tasks import run_review_session
    result = await run_review_session(db, user_id, payload)
    return result, (result.get("summary", "") or "Review session completed.")[:300]


async def _dispatch_reentry_session(db, task_id, user_id, payload) -> DispatchResult:
    from services.agent.agenda_tasks import run_reentry_session
    result = await run_reentry_session(db, user_id, payload)
    return result, (result.get("summary", "") or "Re-entry session prepared.")[:300]


async def _dispatch_guided_session(db, task_id, user_id, payload) -> DispatchResult:
    from services.agent.guided_session import prepare_guided_session
    payload["task_id"] = str(task_id)
    result = await prepare_guided_session(db, user_id, payload)
    return result, (result.get("summary", "") or "Guided session prepared.")[:300]


async def _dispatch_generate_quiz_entry(db, task_id, user_id, payload) -> DispatchResult:
    return await _dispatch_generate_quiz(db, user_id, payload)


async def _dispatch_create_flashcards_entry(db, task_id, user_id, payload) -> DispatchResult:
    return await _dispatch_create_flashcards(db, user_id, payload)


async def _dispatch_code_execution_entry(db, task_id, user_id, payload) -> DispatchResult:
    return await _dispatch_code_execution(payload)


# The dispatch table. ``SUPPORTED_TASK_TYPES`` (services.activity.task_types)
# mirrors its keys and is what submit_task validates against.
TASK_HANDLERS = {
    "generate_quiz": _dispatch_generate_quiz_entry,
    "create_flashcard": _dispatch_create_flashcards_entry,
    "create_flashcards": _dispatch_create_flashcards_entry,
    "multi_step": _dispatch_multi_step,
    "chat_post_process": _dispatch_chat_post_process,
    "code_execution": _dispatch_code_execution_entry,
    "memory_consolidation": _dispatch_memory_consolidation,
    "review_session": _dispatch_review_session,
    "reentry_session": _dispatch_reentry_session,
    "guided_session": _dispatch_guided_session,
}


async def dispatch_task(
    *,
    task_id: uuid.UUID,
    task_type: str,
    user_id: uuid.UUID,
    payload: JsonObject,
) -> DispatchResult:
    """Route a task to the correct handler based on task_type."""
    handler = TASK_HANDLERS.get(task_type)
    if handler is None:
        raise ValueError(f"Unsupported task_type: {task_type}")

    async with async_session() as db:
        if task_type in _LLM_TASK_LABELS:
            from services.llm.readiness import ensure_llm_ready
            await ensure_llm_ready(_LLM_TASK_LABELS[task_type])
        return await handler(db, task_id, user_id, payload)


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
    outcome = await extract_questions(content, title, course_id)
    persisted = outcome.problems[:count]
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
