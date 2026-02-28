"""WF-4: Study Session Workflow.

Delegates to the multi-agent orchestrator so chat and workflow entry points
share the same routing, context loading, reflection, and post-processing path.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

async def run_study_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    user_message: str,
) -> dict:
    """Execute the WF-4 study session workflow via the shared orchestrator."""
    from database import async_session
    from services.agent.orchestrator import run_agent_turn

    ctx = await run_agent_turn(
        user_id=user_id,
        course_id=course_id,
        message=user_message,
        db=db,
        db_factory=async_session,
        scene="study_session",
        post_process_inline=True,
    )
    return {
        "response": ctx.response,
        "intent": ctx.intent.value,
        "agent": ctx.delegated_agent,
        "memories_used": len(ctx.memories),
        "content_docs_used": len(ctx.content_docs),
        "signal_extracted": ctx.extracted_signal is not None,
    }
