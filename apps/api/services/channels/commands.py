"""Channel command parser — slash-command interface for messaging channels.

Messaging users don't have a GUI, so they interact via text commands:
  /help      — list available commands
  /courses   — list enrolled courses
  /switch N  — switch active course by number or name
  /scene X   — switch to a different scene
  /current   — show active course + scene
  /status    — brief learning progress summary
"""

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.channel_binding import ChannelBinding
from models.user import User

logger = logging.getLogger(__name__)

# Valid scene IDs (v3 preset scenes)
VALID_SCENES = {
    "study_session",
    "exam_prep",
    "assignment",
    "review_drill",
    "note_organize",
}

COMMANDS = {
    "/help": "Show available commands",
    "/courses": "List your courses",
    "/switch": "Switch active course — /switch <number or name>",
    "/scene": "Switch scene — /scene <scene_name>",
    "/current": "Show active course and scene",
    "/status": "Brief learning progress summary",
}


@dataclass
class ParsedCommand:
    """Result of parsing a slash command from message text."""

    name: str       # Command name without slash, e.g. "help", "switch"
    args: str       # Everything after the command name, stripped


def parse_command(text: str) -> ParsedCommand | None:
    """Detect and parse a slash command from message text.

    Returns None if the text is not a command.
    Only the first word is checked; commands are case-insensitive.
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    parts = stripped.split(None, 1)
    cmd_name = parts[0].lower()

    # Validate against known commands
    if cmd_name not in COMMANDS:
        return None

    args = parts[1].strip() if len(parts) > 1 else ""
    return ParsedCommand(name=cmd_name.lstrip("/"), args=args)


async def execute_command(
    cmd: ParsedCommand,
    user: User,
    binding: ChannelBinding,
    db: AsyncSession,
) -> str:
    """Dispatch a parsed command to its handler and return the response text."""
    handlers = {
        "help": _show_help,
        "courses": _list_courses,
        "switch": _switch_course,
        "scene": _switch_scene,
        "current": _show_current,
        "status": _show_status,
    }

    handler = handlers.get(cmd.name)
    if handler is None:
        return f"Unknown command: /{cmd.name}\nType /help for available commands."

    try:
        return await handler(cmd, user, binding, db)
    except Exception as exc:
        logger.error("Command /%s failed: %s", cmd.name, exc, exc_info=True)
        return f"Command /{cmd.name} failed. Please try again."


async def _show_help(
    cmd: ParsedCommand,
    user: User,
    binding: ChannelBinding,
    db: AsyncSession,
) -> str:
    """Show available commands."""
    lines = ["*Available Commands*", ""]
    for command, description in COMMANDS.items():
        lines.append(f"  {command} — {description}")
    lines.append("")
    lines.append("Send any other message to chat with your tutor.")
    return "\n".join(lines)


async def _list_courses(
    cmd: ParsedCommand,
    user: User,
    binding: ChannelBinding,
    db: AsyncSession,
) -> str:
    """Query and format the user's courses as a numbered list."""
    stmt = (
        select(Course)
        .where(Course.user_id == user.id)
        .order_by(Course.created_at.desc())
    )
    result = await db.execute(stmt)
    courses = result.scalars().all()

    if not courses:
        return (
            "You don't have any courses yet.\n"
            "Create a course on the web app first, then come back here!"
        )

    lines = ["*Your Courses*", ""]
    for i, course in enumerate(courses, 1):
        active_marker = " (active)" if binding.active_course_id == course.id else ""
        scene_label = f" [{course.active_scene or 'study_session'}]"
        lines.append(f"  {i}. {course.name}{scene_label}{active_marker}")

    lines.append("")
    lines.append("Use /switch <number> to change your active course.")
    return "\n".join(lines)


async def _switch_course(
    cmd: ParsedCommand,
    user: User,
    binding: ChannelBinding,
    db: AsyncSession,
) -> str:
    """Switch the binding's active course by number or fuzzy name match."""
    if not cmd.args:
        return "Usage: /switch <course number or name>\nType /courses to see the list."

    # Load user's courses
    stmt = (
        select(Course)
        .where(Course.user_id == user.id)
        .order_by(Course.created_at.desc())
    )
    result = await db.execute(stmt)
    courses = result.scalars().all()

    if not courses:
        return "You don't have any courses. Create one on the web app first."

    target = cmd.args.strip()

    # Try numeric index first
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(courses):
            course = courses[idx]
            binding.active_course_id = course.id
            await db.flush()
            return f"Switched to: *{course.name}* [{course.active_scene or 'study_session'}]"
        return f"Invalid number. You have {len(courses)} course(s). Type /courses to see them."

    # Fuzzy name match using thefuzz
    try:
        from thefuzz import fuzz
    except ImportError:
        # Fallback to case-insensitive substring match
        target_lower = target.lower()
        for course in courses:
            if target_lower in course.name.lower():
                binding.active_course_id = course.id
                await db.flush()
                return f"Switched to: *{course.name}* [{course.active_scene or 'study_session'}]"
        return f"No course matching '{target}'. Type /courses to see your courses."

    best_match = None
    best_score = 0
    for course in courses:
        score = fuzz.partial_ratio(target.lower(), course.name.lower())
        if score > best_score:
            best_score = score
            best_match = course

    if best_match and best_score >= 60:
        binding.active_course_id = best_match.id
        await db.flush()
        return f"Switched to: *{best_match.name}* [{best_match.active_scene or 'study_session'}]"

    return f"No course matching '{target}' (best match score: {best_score}). Type /courses to see your courses."


async def _show_current(
    cmd: ParsedCommand,
    user: User,
    binding: ChannelBinding,
    db: AsyncSession,
) -> str:
    """Show the active course name and scene."""
    if not binding.active_course_id:
        return "No active course selected.\nType /courses to see your courses, then /switch <number> to select one."

    stmt = select(Course).where(Course.id == binding.active_course_id)
    result = await db.execute(stmt)
    course = result.scalar_one_or_none()

    if course is None:
        binding.active_course_id = None
        await db.flush()
        return "Your previously active course was deleted.\nType /courses to select a new one."

    scene = course.active_scene or "study_session"
    lines = [
        "*Current Session*",
        "",
        f"  Course: {course.name}",
        f"  Scene: {scene}",
    ]
    if course.description:
        lines.append(f"  Description: {course.description[:100]}")
    return "\n".join(lines)


async def _switch_scene(
    cmd: ParsedCommand,
    user: User,
    binding: ChannelBinding,
    db: AsyncSession,
) -> str:
    """Validate scene name and update the active course's scene."""
    if not cmd.args:
        scene_list = ", ".join(sorted(VALID_SCENES))
        return f"Usage: /scene <scene_name>\nAvailable scenes: {scene_list}"

    if not binding.active_course_id:
        return "No active course. Use /switch to select a course first."

    scene_name = cmd.args.strip().lower().replace(" ", "_")

    if scene_name not in VALID_SCENES:
        scene_list = ", ".join(sorted(VALID_SCENES))
        return f"Unknown scene: '{scene_name}'\nAvailable scenes: {scene_list}"

    # Load and update the course
    stmt = select(Course).where(Course.id == binding.active_course_id)
    result = await db.execute(stmt)
    course = result.scalar_one_or_none()

    if course is None:
        binding.active_course_id = None
        await db.flush()
        return "Active course not found. Use /courses to select a new one."

    old_scene = course.active_scene or "study_session"
    course.active_scene = scene_name
    await db.flush()

    return f"Scene changed: {old_scene} -> *{scene_name}*\nCourse: {course.name}"


async def _show_status(
    cmd: ParsedCommand,
    user: User,
    binding: ChannelBinding,
    db: AsyncSession,
) -> str:
    """Show a brief learning progress summary for the active course."""
    if not binding.active_course_id:
        return "No active course. Use /switch to select a course first."

    stmt = select(Course).where(Course.id == binding.active_course_id)
    result = await db.execute(stmt)
    course = result.scalar_one_or_none()

    if course is None:
        binding.active_course_id = None
        await db.flush()
        return "Active course not found. Use /courses to select a new one."

    # Query learning progress summary
    from models.progress import LearningProgress

    progress_stmt = select(
        sa_func.count(LearningProgress.id).label("total"),
        sa_func.avg(LearningProgress.mastery_score).label("avg_mastery"),
        sa_func.sum(LearningProgress.time_spent_minutes).label("total_time"),
        sa_func.sum(LearningProgress.quiz_attempts).label("total_quizzes"),
        sa_func.sum(LearningProgress.quiz_correct).label("total_correct"),
    ).where(
        LearningProgress.user_id == user.id,
        LearningProgress.course_id == course.id,
    )
    progress_result = await db.execute(progress_stmt)
    row = progress_result.one()

    total_nodes = row.total or 0
    avg_mastery = row.avg_mastery or 0.0
    total_time = row.total_time or 0
    total_quizzes = row.total_quizzes or 0
    total_correct = row.total_correct or 0
    accuracy = (total_correct / total_quizzes * 100) if total_quizzes > 0 else 0

    lines = [
        f"*{course.name}* — Progress Summary",
        "",
        f"  Scene: {course.active_scene or 'study_session'}",
        f"  Topics tracked: {total_nodes}",
        f"  Avg mastery: {avg_mastery:.0%}",
        f"  Study time: {total_time} min",
        f"  Quiz accuracy: {total_correct}/{total_quizzes} ({accuracy:.0f}%)",
    ]
    return "\n".join(lines)
