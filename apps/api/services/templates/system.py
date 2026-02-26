"""Built-in learning templates.

5 built-in templates (spec Phase 1) + user-created templates.
Templates define default preferences for specific learning styles.
"""

import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.progress import LearningTemplate
from services.preference.engine import save_preference

logger = logging.getLogger(__name__)

# 5 built-in templates (spec requirement)
BUILTIN_TEMPLATES = [
    {
        "name": "STEM Student",
        "description": "Optimized for math, physics, CS, and engineering courses. "
                       "Emphasizes step-by-step problem solving and diagrams.",
        "target_audience": "STEM student",
        "tags": ["math", "physics", "cs", "engineering"],
        "preferences": {
            "note_format": "step_by_step",
            "detail_level": "detailed",
            "explanation_style": "step_by_step",
            "visual_preference": "diagrams",
            "quiz_difficulty": "adaptive",
            "language": "en",
        },
    },
    {
        "name": "Humanities Scholar",
        "description": "Designed for literature, history, philosophy courses. "
                       "Emphasizes summaries, critical thinking, and discussion.",
        "target_audience": "Humanities student",
        "tags": ["literature", "history", "philosophy", "arts"],
        "preferences": {
            "note_format": "summary",
            "detail_level": "detailed",
            "explanation_style": "conversational",
            "visual_preference": "minimal",
            "quiz_difficulty": "moderate",
            "language": "en",
        },
    },
    {
        "name": "Language Learner",
        "description": "Optimized for foreign language courses. "
                       "Uses tables for vocabulary and example-heavy explanations.",
        "target_audience": "Language student",
        "tags": ["language", "vocabulary", "grammar"],
        "preferences": {
            "note_format": "table",
            "detail_level": "balanced",
            "explanation_style": "example_heavy",
            "visual_preference": "auto",
            "quiz_difficulty": "easy",
            "language": "auto",
        },
    },
    {
        "name": "Visual Learner",
        "description": "For students who learn best with diagrams and visual aids. "
                       "Maximizes mind maps and visual content.",
        "target_audience": "Visual learner",
        "tags": ["visual", "diagrams", "mind_maps"],
        "preferences": {
            "note_format": "mind_map",
            "detail_level": "balanced",
            "explanation_style": "step_by_step",
            "visual_preference": "maximum",
            "quiz_difficulty": "adaptive",
            "language": "en",
        },
    },
    {
        "name": "Quick Reviewer",
        "description": "For exam preparation and fast review. "
                       "Concise bullet points with focus on key concepts.",
        "target_audience": "Exam prep",
        "tags": ["exam", "review", "quick"],
        "preferences": {
            "note_format": "bullet_point",
            "detail_level": "concise",
            "explanation_style": "formal",
            "visual_preference": "minimal",
            "quiz_difficulty": "hard",
            "language": "en",
        },
    },
]


async def seed_builtin_templates(db: AsyncSession) -> int:
    """Seed the built-in templates if they don't exist."""
    created = 0
    for template_data in BUILTIN_TEMPLATES:
        result = await db.execute(
            select(LearningTemplate).where(
                LearningTemplate.name == template_data["name"],
                LearningTemplate.is_builtin == True,
            )
        )
        if result.scalar_one_or_none():
            continue

        template = LearningTemplate(
            name=template_data["name"],
            description=template_data["description"],
            is_builtin=True,
            target_audience=template_data["target_audience"],
            tags=template_data["tags"],
            preferences=template_data["preferences"],
        )
        db.add(template)
        created += 1

    if created:
        await db.flush()
    return created


async def apply_template(
    db: AsyncSession,
    user_id: uuid.UUID,
    template_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict:
    """Apply a learning template's preferences to the user.

    If course_id is given, applies at course level.
    Otherwise applies at global level.
    """
    result = await db.execute(
        select(LearningTemplate).where(LearningTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        return {"error": "Template not found"}

    scope = "course" if course_id else "template"

    for dimension, value in template.preferences.items():
        await save_preference(
            db,
            user_id=user_id,
            dimension=dimension,
            value=value,
            scope=scope,
            course_id=course_id,
            source="template",
            confidence=0.3,
        )

    return {
        "template": template.name,
        "applied_preferences": len(template.preferences),
        "scope": scope,
    }


async def list_templates(db: AsyncSession) -> list[dict]:
    """List all available templates."""
    result = await db.execute(
        select(LearningTemplate).order_by(
            LearningTemplate.is_builtin.desc(),
            LearningTemplate.name,
        )
    )
    templates = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "description": t.description,
            "is_builtin": t.is_builtin,
            "target_audience": t.target_audience,
            "tags": t.tags,
            "preferences": t.preferences,
        }
        for t in templates
    ]
