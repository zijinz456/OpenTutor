"""Seed preset scenes into the database.

2 preset scenes: study_session, exam_prep.
Run on app startup or via Alembic data migration.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.scene import Scene

logger = logging.getLogger(__name__)

PRESET_SCENES = [
    {
        "scene_id": "study_session",
        "display_name": "Daily Study",
        "icon": "",
        "is_preset": True,
        "tab_preset": [
            {"type": "notes", "position": 0},
            {"type": "quiz", "position": 1},
            {"type": "chat", "position": 2},
        ],
        "workflow": "study",
        "ai_behavior": {"style": "thorough", "encourage_exploration": True},
        "preferences": None,
    },
    {
        "scene_id": "exam_prep",
        "display_name": "Exam Prep",
        "icon": "",
        "is_preset": True,
        "tab_preset": [
            {"type": "plan", "position": 0},
            {"type": "quiz", "position": 1},
            {"type": "review", "position": 2},
            {"type": "chat", "position": 3},
        ],
        "workflow": "exam",
        "ai_behavior": {"style": "concise", "focus": "weak_points", "quiz_priority": "high_freq"},
        "preferences": {"detail_level": "concise", "note_format": "bullet_point"},
    },
]


async def seed_preset_scenes(db: AsyncSession) -> None:
    """Insert preset scenes if they don't already exist."""
    for scene_data in PRESET_SCENES:
        result = await db.execute(
            select(Scene).where(Scene.scene_id == scene_data["scene_id"])
        )
        existing = result.scalar_one_or_none()
        if existing:
            continue

        scene = Scene(**scene_data)
        db.add(scene)
        logger.info("Seeded preset scene: %s", scene_data["scene_id"])
