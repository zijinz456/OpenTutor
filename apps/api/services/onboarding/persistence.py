"""Persist onboarding results to preferences and memory.

Dual storage pattern (Mem0):
1. Structured preferences -> queried by Block Decision Engine
2. Natural language memory -> retrieved by agents via semantic search
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.learner_profile import LearnerProfile
from schemas.preference import PreferenceCreate

logger = logging.getLogger(__name__)


def profile_to_preferences(profile: LearnerProfile) -> list[PreferenceCreate]:
    """Convert a LearnerProfile to preference records."""
    prefs: list[PreferenceCreate] = []
    for field_name, value in profile.preferences.model_dump().items():
        prefs.append(PreferenceCreate(
            dimension=field_name,
            value=str(value),
            source="onboarding_interview",
        ))
    for field_name, value in profile.behavior.model_dump().items():
        prefs.append(PreferenceCreate(
            dimension=field_name,
            value=str(value),
            source="onboarding_interview",
        ))
    if profile.learning_goal:
        prefs.append(PreferenceCreate(
            dimension="learning_goal",
            value=profile.learning_goal,
            source="onboarding_interview",
        ))
    if profile.background_level != "unknown":
        prefs.append(PreferenceCreate(
            dimension="background_level",
            value=profile.background_level,
            source="onboarding_interview",
        ))
    return prefs


async def persist_onboarding_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    profile: LearnerProfile,
) -> None:
    """Store profile in both preferences and memory."""
    # 1. Structured preferences
    preferences = profile_to_preferences(profile)
    from services.preference.engine import save_preference

    for pref in preferences:
        try:
            await save_preference(
                db,
                user_id=user_id,
                dimension=pref.dimension,
                value=pref.value,
                scope=pref.scope,
                course_id=course_id,
                source=pref.source,
                confidence=profile.confidence,
            )
        except Exception:
            logger.warning("Failed to set preference %s", pref.dimension, exc_info=True)

    # 2. Natural language memory
    summary = _build_profile_summary(profile)
    try:
        from services.memory.pipeline import encode_memory, generate_embedding
        from models.memory import ConversationMemory
        from services.search.compat import update_search_vector

        embedding = await generate_embedding(summary)
        memory = ConversationMemory(
            user_id=user_id,
            course_id=course_id,
            summary=summary,
            memory_type="profile",
            embedding=embedding,
            importance=0.9,
            source_message=profile.raw_description[:200] if profile.raw_description else "onboarding",
            metadata_json={"source": "onboarding_interview"},
        )
        db.add(memory)
        await db.flush()
        await update_search_vector(db, "conversation_memories", str(memory.id), summary)
        await db.flush()
        logger.info("Onboarding profile memory stored for user %s", user_id)
    except Exception:
        logger.warning("Failed to store onboarding memory", exc_info=True)
        await db.rollback()

    await db.commit()


def _build_profile_summary(profile: LearnerProfile) -> str:
    """Build a natural-language summary for memory storage."""
    parts: list[str] = []

    style_names = {
        "visual": "视觉化学习", "reading": "阅读笔记型",
        "kinesthetic": "实践操作型", "mixed": "综合型",
    }
    parts.append(f"学习风格：{style_names.get(profile.behavior.learning_style, '综合型')}")

    if profile.preferences.prefers_visual_aids:
        parts.append("偏好思维导图和知识图谱")
    if profile.preferences.prefers_note_taking:
        parts.append("喜欢做笔记整理")
    if profile.preferences.prefers_active_recall:
        parts.append("通过做题巩固知识")
    if profile.preferences.prefers_spaced_review:
        parts.append("重视间隔复习")
    if profile.preferences.prefers_mistake_analysis:
        parts.append("注重错题分析")
    if profile.preferences.prefers_planning:
        parts.append("喜欢制定学习计划")

    duration_names = {"short": "短时间(30分钟内)", "medium": "中等时长(30-60分钟)", "long": "长时间(60分钟以上)"}
    parts.append(f"每次学习{duration_names.get(profile.behavior.session_duration, '中等时长')}")

    if profile.learning_goal:
        parts.append(f"学习目标：{profile.learning_goal}")

    if profile.raw_description:
        parts.append(f"自述：{profile.raw_description[:100]}")

    return "。".join(parts)
