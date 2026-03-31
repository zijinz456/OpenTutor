"""Preference tools — allow the Tutor agent to proactively save user preferences.

Inspired by Letta's core_memory_append: when the user explicitly expresses how
they want to learn, the agent can call save_user_preference immediately instead
of waiting for the post-process pipeline.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import ToolCategory, ToolResult, param, tool

logger = logging.getLogger(__name__)

VALID_DIMENSIONS = {
    "note_format",
    "detail_level",
    "explanation_style",
    "visual_preference",
    "language",
}


@tool(
    name="save_user_preference",
    description=(
        "Save a learning preference explicitly stated by the user. "
        "Call this when the user says how they want to learn "
        "(e.g., 'I prefer examples', 'please use diagrams', 'I find theory hard', "
        "'I like concise answers'). "
        "This records the preference immediately so it applies to all future responses. "
        "Do NOT call for normal study questions — only when the user expresses a personal preference."
    ),
    domain="education",
    category=ToolCategory.WRITE,
    params=[
        param(
            "dimension",
            "string",
            "Preference category: note_format, detail_level, explanation_style, visual_preference, or language",
            required=True,
            enum=["note_format", "detail_level", "explanation_style", "visual_preference", "language"],
        ),
        param(
            "value",
            "string",
            (
                "The preference value. "
                "note_format: bullet_point|table|mind_map|step_by_step|summary. "
                "detail_level: concise|balanced|detailed. "
                "explanation_style: formal|conversational|socratic|example_heavy. "
                "visual_preference: auto|text_heavy|diagram_heavy|mixed. "
                "language: en|zh|auto."
            ),
            required=True,
        ),
        param(
            "reason",
            "string",
            "Brief reason extracted from user's message (e.g., 'user said I prefer bullet points').",
            required=False,
        ),
    ],
)
async def save_user_preference(
    parameters: dict, ctx, db: AsyncSession
) -> ToolResult:
    from models.preference import PreferenceSignal
    from services.preference.confidence import process_signal_to_preference

    dimension = parameters.get("dimension", "").strip()
    value = parameters.get("value", "").strip()
    reason = parameters.get("reason", "").strip()

    if dimension not in VALID_DIMENSIONS:
        return ToolResult(
            success=False,
            output="",
            error=f"Invalid dimension '{dimension}'. Must be one of: {', '.join(sorted(VALID_DIMENSIONS))}",
        )
    if not value:
        return ToolResult(success=False, output="", error="value is required.")

    user_id: uuid.UUID = ctx.user_id
    course_id: uuid.UUID | None = getattr(ctx, "course_id", None)

    # Record the explicit signal
    signal = PreferenceSignal(
        user_id=user_id,
        course_id=course_id,
        signal_type="explicit",
        dimension=dimension,
        value=value,
        context={"source": "agent_tool", "reason": reason} if reason else {"source": "agent_tool"},
    )
    db.add(signal)
    await db.flush()

    # Immediately attempt promotion (fast-path will kick in for explicit signals)
    promoted = await process_signal_to_preference(db, user_id, dimension, course_id)

    if promoted:
        logger.info(
            "Preference saved and promoted: user=%s dim=%s val=%s confidence=%.2f",
            user_id, dimension, value, promoted.confidence,
        )
        return ToolResult(
            success=True,
            output=(
                f"Preference saved: {dimension} = {value} "
                f"(confidence {promoted.confidence:.0%}). "
                "I'll apply this to all future responses."
            ),
        )

    logger.info("Preference signal recorded: user=%s dim=%s val=%s (pending promotion)", user_id, dimension, value)
    return ToolResult(
        success=True,
        output=f"Preference noted: {dimension} = {value}. I'll keep this in mind.",
    )
