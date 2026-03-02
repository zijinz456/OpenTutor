"""iCal (.ics) export from GeneratedAsset study plans.

Uses the icalendar library to produce importable calendar files with study
session events derived from AI-generated study plans.
"""

import logging
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def export_study_plan_to_ical(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    plan_batch_id: uuid.UUID | None = None,
) -> Path:
    """Export a study plan as an iCal .ics file.

    Returns the path to a temporary .ics file. Caller is responsible for cleanup.
    """
    from icalendar import Calendar, Event

    from models.generated_asset import GeneratedAsset
    from models.course import Course

    # Get course name
    course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one_or_none()
    course_name = course.name if course else "OpenTutor"

    # Fetch study plan assets
    stmt = select(GeneratedAsset).where(
        GeneratedAsset.user_id == user_id,
        GeneratedAsset.course_id == course_id,
        GeneratedAsset.asset_type == "study_plan",
        GeneratedAsset.is_archived == False,  # noqa: E712
    )
    if plan_batch_id:
        stmt = stmt.where(GeneratedAsset.batch_id == plan_batch_id)

    # Get the most recent plan
    stmt = stmt.order_by(GeneratedAsset.created_at.desc()).limit(1)
    result = await db.execute(stmt)
    plan_asset = result.scalar_one_or_none()

    if not plan_asset:
        raise ValueError("No study plan found to export.")

    # Build iCal
    cal = Calendar()
    cal.add("prodid", "-//OpenTutor//Study Plan//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", f"OpenTutor - {course_name}")

    content = plan_asset.content or {}
    steps = content.get("steps", content.get("plan", []))
    if isinstance(steps, dict):
        steps = steps.get("steps", [])

    MAX_EVENTS = 365
    event_count = 0
    now = datetime.now(timezone.utc)

    for i, step in enumerate(steps[:MAX_EVENTS]):
        if not isinstance(step, dict):
            continue

        event = Event()

        # Title
        title = step.get("title", step.get("topic", f"Study Session {i + 1}"))
        event.add("summary", f"{course_name}: {title}")

        # Description
        desc_parts = []
        if step.get("description"):
            desc_parts.append(step["description"])
        if step.get("objectives"):
            desc_parts.append(f"Objectives: {step['objectives']}")
        if step.get("resources"):
            desc_parts.append(f"Resources: {step['resources']}")
        event.add("description", "\n".join(desc_parts) if desc_parts else title)

        # Timing: use scheduled_at if available, otherwise spread from now
        scheduled_at = step.get("scheduled_at", step.get("date"))
        try:
            duration_min = max(5, min(int(step.get("duration", step.get("duration_minutes", 30))), 480))
        except (ValueError, TypeError):
            duration_min = 30

        if scheduled_at:
            try:
                if isinstance(scheduled_at, str):
                    dtstart = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
                else:
                    dtstart = scheduled_at
            except (ValueError, TypeError):
                dtstart = now + timedelta(days=i)
        else:
            # Spread sessions 1 day apart starting from now
            dtstart = now + timedelta(days=i)

        event.add("dtstart", dtstart)
        event.add("dtend", dtstart + timedelta(minutes=duration_min))
        event.add("uid", f"opentutor-{plan_asset.id}-step-{i}@opentutor.local")

        cal.add_component(event)
        event_count += 1

    if event_count == 0:
        raise ValueError("Study plan has no exportable steps.")

    # Write to temp file
    tmp = tempfile.NamedTemporaryFile(suffix=".ics", delete=False)
    tmp_path = Path(tmp.name)
    try:
        tmp.write(cal.to_ical())
        tmp.close()
    except Exception:
        tmp.close()
        tmp_path.unlink(missing_ok=True)
        raise

    logger.info("Exported %d study events to iCal for course %s", event_count, course_id)
    return tmp_path
