"""WF-1: Semester Initialization Workflow.

Flow: create_semester → sync_courses → setup_preferences → generate_plan

Reference from spec:
- WF-1 runs at the start of each semester
- Syncs course data from Canvas (or manual input)
- Sets up per-course preference defaults
- Generates initial study plan
"""

import uuid
import logging
from datetime import datetime, timedelta
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from services.llm.router import get_llm_client
from services.preference.engine import save_preference

logger = logging.getLogger(__name__)


class SemesterInitState(TypedDict):
    user_id: uuid.UUID
    semester_name: str
    courses: list[dict]
    plan: str


async def create_courses(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_list: list[dict],
) -> list[Course]:
    """Create courses from user input or Canvas sync."""
    created = []
    for course_data in course_list:
        # Check if course already exists
        result = await db.execute(
            select(Course).where(
                Course.user_id == user_id,
                Course.name == course_data["name"],
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            created.append(existing)
            continue

        course = Course(
            user_id=user_id,
            name=course_data["name"],
            description=course_data.get("description", ""),
            metadata_=course_data.get("metadata", {}),
        )
        db.add(course)
        created.append(course)

    await db.flush()
    return created


async def setup_course_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
    course: Course,
    course_type: str | None = None,
) -> None:
    """Set up initial preferences based on course type.

    STEM courses → step_by_step + diagrams
    Humanities → summary + bullet_point
    Language → conversational + example_heavy
    """
    presets = {
        "stem": {
            "note_format": "step_by_step",
            "explanation_style": "step_by_step",
            "visual_preference": "diagrams",
            "detail_level": "detailed",
        },
        "humanities": {
            "note_format": "bullet_point",
            "explanation_style": "conversational",
            "visual_preference": "minimal",
            "detail_level": "balanced",
        },
        "language": {
            "note_format": "table",
            "explanation_style": "example_heavy",
            "visual_preference": "auto",
            "detail_level": "balanced",
        },
    }

    preset = presets.get(course_type or "stem", presets["stem"])

    for dimension, value in preset.items():
        await save_preference(
            db,
            user_id=user_id,
            dimension=dimension,
            value=value,
            scope="course",
            course_id=course.id,
            source="onboarding",
            confidence=0.3,
        )


async def generate_semester_plan(
    db: AsyncSession,
    user_id: uuid.UUID,
    courses: list[Course],
) -> str:
    """Generate an initial semester study plan using LLM."""
    client = get_llm_client()

    course_list = "\n".join(
        f"- {c.name}: {c.description or 'No description'}"
        for c in courses
    )

    prompt = f"""Based on these courses, create a weekly study plan template:

Courses:
{course_list}

Requirements:
1. Distribute study time evenly
2. Include review sessions
3. Leave buffer time for assignments
4. Include weekend review blocks
5. Output in a clean markdown format

Keep the plan concise and actionable."""

    plan, _ = await client.chat(
        "You are a study planning assistant. Create practical, realistic study plans.",
        prompt,
    )

    return plan


async def run_semester_init(
    db: AsyncSession,
    user_id: uuid.UUID,
    semester_name: str,
    course_list: list[dict],
) -> dict:
    """Execute WF-1: Semester initialization.

    Steps:
    1. Create courses in DB
    2. Set up course-level preference defaults
    3. Generate semester study plan
    """
    # Step 1: Create courses
    courses = await create_courses(db, user_id, course_list)

    # Step 2: Set up preferences per course
    for i, course in enumerate(courses):
        course_type = course_list[i].get("type", "stem")
        await setup_course_preferences(db, user_id, course, course_type)

    # Step 3: Generate study plan
    plan = await generate_semester_plan(db, user_id, courses)

    return {
        "semester": semester_name,
        "courses_created": len(courses),
        "course_ids": [str(c.id) for c in courses],
        "plan": plan,
    }
