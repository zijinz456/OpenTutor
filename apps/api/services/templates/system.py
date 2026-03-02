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
        "description": (
            "Optimized for math, physics, computer science, and engineering courses. "
            "Delivers step-by-step derivations with detailed intermediate reasoning so "
            "you can follow every logical leap. Proofs, formulas, and algorithms are "
            "broken into numbered stages with diagrams generated automatically when "
            "spatial intuition helps. Quiz difficulty adapts to your performance — "
            "easy problems build confidence, harder ones stretch understanding."
        ),
        "target_audience": "STEM student",
        "tags": [
            "math", "physics", "cs", "engineering", "chemistry",
            "problem_solving", "derivation", "proof", "algorithm",
        ],
        "preferences": {
            "note_format": "step_by_step",
            "detail_level": "detailed",
            "explanation_style": "socratic",
            "visual_preference": "diagram_heavy",
            "quiz_difficulty": "adaptive",
            "layout_preset": "balanced",
            "language": "en",
        },
    },
    {
        "name": "Humanities Scholar",
        "description": (
            "Designed for literature, history, philosophy, and social science courses. "
            "Produces rich narrative summaries that connect themes, highlight cause-and-"
            "effect chains, and surface competing interpretations. Explanations are "
            "conversational — the tutor poses open-ended follow-ups to encourage "
            "critical thinking. Visual clutter is minimized so you can focus on close "
            "reading and argumentation. Quizzes favor medium difficulty to balance "
            "recall with analytical depth."
        ),
        "target_audience": "Humanities student",
        "tags": [
            "literature", "history", "philosophy", "arts",
            "social_science", "critical_thinking", "essay", "analysis",
        ],
        "preferences": {
            "note_format": "summary",
            "detail_level": "detailed",
            "explanation_style": "conversational",
            "visual_preference": "text_heavy",
            "quiz_difficulty": "medium",
            "layout_preset": "notesFocused",
            "language": "en",
        },
    },
    {
        "name": "Language Learner",
        "description": (
            "Optimized for foreign language acquisition — vocabulary, grammar, reading, "
            "and conversation practice. Notes are organized as comparison tables "
            "(target language vs. native language) for quick scanning. Explanations are "
            "loaded with real-world example sentences so you see words in context. "
            "Language is set to auto-detect so the tutor can seamlessly switch between "
            "your native language and the target language. Quizzes start easy to build "
            "confidence, with the chat panel front-and-center for conversational drills."
        ),
        "target_audience": "Language student",
        "tags": [
            "language", "vocabulary", "grammar", "pronunciation",
            "conversation", "translation", "reading_comprehension",
        ],
        "preferences": {
            "note_format": "table",
            "detail_level": "balanced",
            "explanation_style": "example_heavy",
            "visual_preference": "auto",
            "quiz_difficulty": "easy",
            "layout_preset": "chatFocused",
            "language": "auto",
        },
    },
    {
        "name": "Visual Learner",
        "description": (
            "For students who absorb information best through diagrams, mind maps, "
            "flowcharts, and other visual structures. Notes are generated as mind maps "
            "that branch from core concepts outward, making relationships between ideas "
            "immediately visible. Every explanation is accompanied by as much visual "
            "content as possible — timelines, comparison charts, process flows. "
            "Quiz difficulty adapts to performance, and the layout keeps notes and "
            "visuals balanced on screen."
        ),
        "target_audience": "Visual learner",
        "tags": [
            "visual", "diagrams", "mind_maps", "flowchart",
            "infographic", "spatial", "graphic_organizer",
        ],
        "preferences": {
            "note_format": "mind_map",
            "detail_level": "balanced",
            "explanation_style": "example_heavy",
            "visual_preference": "maximum",
            "quiz_difficulty": "adaptive",
            "layout_preset": "balanced",
            "language": "en",
        },
    },
    {
        "name": "Quick Reviewer",
        "description": (
            "Built for exam preparation, last-minute review, and spaced-repetition "
            "sessions. Notes are distilled to concise bullet points — no fluff, only "
            "key definitions, formulas, and must-know facts. Explanations are formal "
            "and to-the-point so you spend zero time on tangents. Quizzes are set to "
            "hard by default to simulate exam pressure and expose weak spots fast. "
            "The quiz panel takes center stage in the layout so you can drill "
            "continuously."
        ),
        "target_audience": "Exam prep",
        "tags": [
            "exam", "review", "quick", "spaced_repetition",
            "flashcard", "cram", "finals", "midterm",
        ],
        "preferences": {
            "note_format": "bullet_point",
            "detail_level": "concise",
            "explanation_style": "formal",
            "visual_preference": "minimal",
            "quiz_difficulty": "hard",
            "layout_preset": "quizFocused",
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
