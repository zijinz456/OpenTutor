"""Central message dispatcher — routes incoming channel messages through the agent pipeline.

Orchestrates the full lifecycle of an inbound message:
1. Resolve user identity (auto-create if new)
2. Check for slash commands
3. Validate active course context
4. Send typing indicator
5. Download media attachments
6. Run the agent turn (teaching/exercise/planning/etc.)
7. Format response for the channel
8. Update last_message_at timestamp
9. Send the response
"""

import logging

from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.channels.base import BaseChannelAdapter, IncomingMessage, OutgoingMessage
from services.channels.identity import resolve_or_create_user
from services.channels.commands import parse_command, execute_command
from services.channels.formatter import format_for_channel

logger = logging.getLogger(__name__)


async def dispatch_message(
    adapter: BaseChannelAdapter,
    incoming: IncomingMessage,
    db: AsyncSession,
    db_factory,
) -> None:
    """Process an incoming channel message end-to-end.

    Args:
        adapter: The platform adapter that received the message.
        incoming: The parsed incoming message.
        db: Active database session for the request lifecycle.
        db_factory: Async session factory for background tasks (post-processing).
    """
    channel_type = incoming.channel_type
    channel_id = incoming.channel_id

    try:
        # 1. Resolve or auto-create user
        user, binding = await resolve_or_create_user(db, channel_type, channel_id)

        # 2. Check for slash commands
        cmd = parse_command(incoming.text)
        if cmd is not None:
            response_text = await execute_command(cmd, user, binding, db)
            await db.commit()
            await adapter.send_message(
                OutgoingMessage(
                    channel_id=channel_id,
                    text=response_text,
                    reply_to_message_id=incoming.message_id,
                )
            )
            return

        # 3. Verify active course context
        if not binding.active_course_id:
            await db.commit()
            await _prompt_course_selection(adapter, user, binding, channel_id, incoming, db)
            return

        # 4. Send typing indicator
        await adapter.send_typing_indicator(channel_id)

        # 5. Download media attachments (if any)
        images = []
        for media_ref in incoming.media:
            try:
                downloaded = await adapter.download_media(
                    media_url=media_ref.get("url"),
                    media_id=media_ref.get("media_id"),
                )
                if downloaded:
                    images.append(downloaded)
            except Exception as exc:
                logger.warning(
                    "Failed to download media from %s: %s",
                    channel_type, exc,
                )

        # 6. Run agent turn
        from services.agent.orchestrator import run_agent_turn

        # Load recent channel conversation history for context
        history = await _load_channel_history(db, user.id, binding.active_course_id)

        ctx = await run_agent_turn(
            user_id=user.id,
            course_id=binding.active_course_id,
            message=incoming.text,
            db=db,
            db_factory=db_factory,
            history=history,
            scene=None,  # Will be resolved from course.active_scene by orchestrator
            post_process_inline=True,
        )

        # 7. Format response for the channel
        response_text = ctx.response or "I'm not sure how to respond to that. Try rephrasing your question."
        formatted = format_for_channel(response_text, channel_type)

        # 8. Update last_message_at
        binding.last_message_at = sa_func.now()
        await db.commit()

        # 9. Send response
        await adapter.send_message(
            OutgoingMessage(
                channel_id=channel_id,
                text=formatted,
                reply_to_message_id=incoming.message_id,
            )
        )

        logger.info(
            "Dispatched %s message for user %s, course %s, agent %s",
            channel_type,
            user.id,
            binding.active_course_id,
            ctx.delegated_agent,
        )

    except Exception as exc:
        logger.error(
            "Message dispatch failed for %s:%s — %s",
            channel_type, channel_id, exc,
            exc_info=True,
        )
        # Best-effort error reply
        await adapter.send_error(channel_id)


async def _prompt_course_selection(
    adapter: BaseChannelAdapter,
    user,
    binding,
    channel_id: str,
    incoming: IncomingMessage,
    db: AsyncSession,
) -> None:
    """Prompt the user to select a course when none is active.

    Checks if the message itself is a course number (quick-select shortcut).
    Otherwise, lists available courses and asks the user to pick one.
    """
    from models.course import Course

    stmt = (
        select(Course)
        .where(Course.user_id == user.id)
        .order_by(Course.created_at.desc())
    )
    result = await db.execute(stmt)
    courses = result.scalars().all()

    if not courses:
        await adapter.send_message(
            OutgoingMessage(
                channel_id=channel_id,
                text=(
                    "Welcome to OpenTutor! You don't have any courses yet.\n\n"
                    "Create a course on the web app first, then come back here "
                    "to study on the go."
                ),
            )
        )
        return

    # Quick-select: if the message is a number, treat it as course selection
    stripped = incoming.text.strip()
    if stripped.isdigit():
        idx = int(stripped) - 1
        if 0 <= idx < len(courses):
            course = courses[idx]
            binding.active_course_id = course.id
            await db.commit()
            await adapter.send_message(
                OutgoingMessage(
                    channel_id=channel_id,
                    text=f"Selected: {course.name}\n\nYou can now start chatting! Type /help for commands.",
                )
            )
            return

    # List courses for selection
    lines = [
        "Welcome to OpenTutor! Please select a course to get started:",
        "",
    ]
    for i, course in enumerate(courses, 1):
        lines.append(f"  {i}. {course.name}")
    lines.append("")
    lines.append("Reply with a number to select a course, or use /switch <name>.")

    await adapter.send_message(
        OutgoingMessage(channel_id=channel_id, text="\n".join(lines))
    )


async def _load_channel_history(
    db: AsyncSession,
    user_id,
    course_id,
    limit: int = 10,
) -> list[dict]:
    """Load recent chat messages for channel conversation context.

    Joins ChatMessageLog through ChatSession to find messages for this
    user + course pair, providing conversational continuity across messages.
    """
    try:
        from models.chat_session import ChatSession
        from models.chat_message import ChatMessageLog

        # Find the most recent session for this user + course
        session_stmt = (
            select(ChatSession.id)
            .where(
                ChatSession.user_id == user_id,
                ChatSession.course_id == course_id,
            )
            .order_by(ChatSession.updated_at.desc())
            .limit(1)
        )
        session_result = await db.execute(session_stmt)
        session_id = session_result.scalar_one_or_none()

        if session_id is None:
            return []

        # Load recent messages from that session
        msg_stmt = (
            select(ChatMessageLog)
            .where(ChatMessageLog.session_id == session_id)
            .order_by(ChatMessageLog.created_at.desc())
            .limit(limit)
        )
        msg_result = await db.execute(msg_stmt)
        messages = msg_result.scalars().all()

        # Reverse to chronological order
        history = []
        for msg in reversed(messages):
            history.append({
                "role": msg.role,
                "content": msg.content,
            })
        return history

    except Exception as exc:
        logger.warning("Failed to load channel history: %s", exc)
        return []
