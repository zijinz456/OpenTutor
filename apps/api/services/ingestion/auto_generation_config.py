"""Auto-configuration for courses after ingestion.

Contains:
- Layout presets (mirror frontend LAYOUT_PRESETS)
- auto_configure_course: Analyze content -> select layout -> generate welcome message

Extracted from auto_generation.py.
"""

import logging
import uuid

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.ingestion import Assignment

logger = logging.getLogger(__name__)

_LAYOUT_PRESETS = {
    "focused": {
        "preset": "focused",
        "sections": [
            {"type": "notes", "position": 0, "visible": False},
            {"type": "practice", "position": 1, "visible": False},
            {"type": "analytics", "position": 2, "visible": False},
            {"type": "plan", "position": 3, "visible": False},
        ],
        "chat_visible": True, "chat_height": 0.65,
        "tree_visible": True, "tree_width": 260,
    },
    "daily_study": {
        "preset": "daily_study",
        "sections": [
            {"type": "notes", "position": 0, "visible": True, "size": "large"},
            {"type": "practice", "position": 1, "visible": True, "size": "medium"},
            {"type": "analytics", "position": 2, "visible": False},
            {"type": "plan", "position": 3, "visible": False},
        ],
        "chat_visible": True, "chat_height": 0.35,
        "tree_visible": True, "tree_width": 240,
    },
    "exam_prep": {
        "preset": "exam_prep",
        "sections": [
            {"type": "notes", "position": 0, "visible": False},
            {"type": "practice", "position": 1, "visible": True, "size": "large"},
            {"type": "analytics", "position": 2, "visible": True, "size": "medium"},
            {"type": "plan", "position": 3, "visible": True, "size": "small"},
        ],
        "chat_visible": True, "chat_height": 0.25,
        "tree_visible": True, "tree_width": 200,
    },
    "assignment": {
        "preset": "assignment",
        "sections": [
            {"type": "notes", "position": 0, "visible": True, "size": "medium"},
            {"type": "practice", "position": 1, "visible": False},
            {"type": "analytics", "position": 2, "visible": False},
            {"type": "plan", "position": 3, "visible": True, "size": "large"},
        ],
        "chat_visible": True, "chat_height": 0.35,
        "tree_visible": True, "tree_width": 240,
    },
}


async def auto_configure_course(
    db_factory,
    course_id: uuid.UUID,
    prep_summary: dict,
) -> dict | None:
    """Analyze ingested course content and auto-configure layout + welcome message."""
    from datetime import datetime, timezone
    from models.content import CourseContentTree
    from models.ingestion import IngestionJob

    async with db_factory() as db:
        assign_result = await db.execute(
            select(Assignment).where(Assignment.course_id == course_id)
        )
        assignments = assign_result.scalars().all()
        deadline_count = sum(1 for a in assignments if a.due_date)

        job_result = await db.execute(
            select(IngestionJob.content_category).where(
                IngestionJob.course_id == course_id,
                IngestionJob.content_category.isnot(None),
            )
        )
        categories = [r[0] for r in job_result.all()]

        node_result = await db.execute(
            select(sa.func.count()).select_from(CourseContentTree).where(
                CourseContentTree.course_id == course_id
            )
        )
        node_count = node_result.scalar() or 0

        course_result = await db.execute(
            select(Course).where(Course.id == course_id)
        )
        course = course_result.scalar_one_or_none()
        if not course:
            return None

        exam_categories = {"exam_schedule", "assignment", "exam"}
        exam_cat_count = sum(1 for c in categories if c in exam_categories)

        if deadline_count >= 3:
            preset_id = "assignment"
        elif exam_cat_count >= 2 or (deadline_count >= 1 and exam_cat_count >= 1):
            preset_id = "exam_prep"
        else:
            preset_id = "focused"

        layout = _LAYOUT_PRESETS[preset_id]

        now = datetime.now(timezone.utc)
        parts = [f"**{course.name}** is ready! Here's what I found:\n"]
        parts.append(f"- **{node_count}** content sections indexed")

        if prep_summary.get("notes", 0) > 0:
            parts.append(f"- **{prep_summary['notes']}** AI-generated note summaries")
        if prep_summary.get("flashcards", 0) > 0:
            parts.append(f"- **{prep_summary['flashcards']}** flashcards created")
        if prep_summary.get("quiz", 0) > 0:
            parts.append(f"- **{prep_summary['quiz']}** quiz questions generated")

        if deadline_count > 0:
            upcoming = [a for a in assignments if a.due_date and a.due_date > now]
            upcoming.sort(key=lambda a: a.due_date)
            parts.append(f"- **{deadline_count}** deadlines detected")
            if upcoming:
                next_due = upcoming[0]
                days_left = (next_due.due_date - now).days
                parts.append(f"- Next deadline: **{next_due.title}** in **{days_left} days**")

        parts.append("")

        if preset_id == "assignment":
            parts.append(
                "I've set up your workspace in **Assignment Mode** with study plan "
                "and deadlines front and center. You can switch modes anytime by asking me."
            )
        elif preset_id == "exam_prep":
            parts.append(
                "I've set up your workspace in **Exam Prep Mode** with practice questions "
                "and analytics visible. Ask me to quiz you or review weak areas."
            )
        else:
            parts.append(
                "Your workspace is ready. "
                "Ask me anything about your materials -- I'll explain, quiz you, or help you review."
            )

        welcome_message = "\n".join(parts)

        metadata = dict(course.metadata_ or {})
        metadata["layout"] = layout
        metadata["welcome_message"] = welcome_message
        metadata["auto_configured_at"] = now.isoformat()
        metadata["auto_config"] = {
            "preset": preset_id,
            "node_count": node_count,
            "deadline_count": deadline_count,
            "categories": categories[:20],
        }
        course.metadata_ = metadata
        await db.commit()

        logger.info(
            "Auto-configured course %s: preset=%s, nodes=%d, deadlines=%d",
            course_id, preset_id, node_count, deadline_count,
        )
        return {"preset": preset_id, "welcome_message": welcome_message}
