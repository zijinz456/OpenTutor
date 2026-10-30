"""Built-in learning templates.

5 built-in preference presets, defined as module constants. Templates define
default preferences for specific learning styles; applying one writes the
preferences through the preference engine.
"""

import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from services.preference.engine import save_preference

logger = logging.getLogger(__name__)

# Namespace for deterministic template IDs (stable across restarts/deploys).
_TEMPLATE_ID_NAMESPACE = uuid.UUID("6f1d8c2e-5b3a-4c7e-9d1f-2a4b6c8e0f13")

# 5 built-in templates (spec requirement)
BUILTIN_TEMPLATES: list[dict] = [
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




def _template_id(name: str) -> uuid.UUID:
    return uuid.uuid5(_TEMPLATE_ID_NAMESPACE, name)


def list_templates() -> list[dict]:
    """List all available (built-in) templates."""
    return [
        {
            "id": str(_template_id(t["name"])),
            "name": t["name"],
            "description": t["description"],
            "is_builtin": True,
            "target_audience": t["target_audience"],
            "tags": list(t["tags"]),
            "preferences": dict(t["preferences"]),
        }
        for t in BUILTIN_TEMPLATES
    ]


def get_template(template_id: uuid.UUID) -> dict | None:
    """Look up a built-in template by its stable ID."""
    for t in BUILTIN_TEMPLATES:
        if _template_id(t["name"]) == template_id:
            return t
    return None


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
    template = get_template(template_id)
    if not template:
        return {"error": "Template not found"}

    scope = "course" if course_id else "template"

    for dimension, value in template["preferences"].items():
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
        "template": template["name"],
        "applied_preferences": len(template["preferences"]),
        "scope": scope,
    }
