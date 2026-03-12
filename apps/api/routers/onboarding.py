"""Onboarding interview endpoint — JSON + preference persistence.

Lightweight chat for the habit interview — bypasses full orchestrator
(no RAG, no block decisions, no course context needed).

Returns JSON responses, extracts LearnerProfile, persists preferences
and memories when onboarding completes.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.course import Course
from models.preference import UserPreference
from models.user import User
from schemas.learner_profile import LearnerProfile
from services.agent.agents.onboarding import OnboardingAgent
from services.agent.state import AgentContext, IntentType, TaskPhase
from services.auth.dependency import get_current_user
from services.block_decision.profile_mapper import profile_to_layout
from services.memory.pipeline import encode_memory
from services.templates.demo_course import DEMO_COURSE_NAME, seed_demo_course

logger = logging.getLogger(__name__)
router = APIRouter()

_onboarding_agent = OnboardingAgent()

# Sentinel course_id for onboarding (no course context yet)
_NIL_COURSE_ID = uuid.UUID(int=0)


class OnboardingRequest(BaseModel):
    message: str = Field(default="", max_length=2000)
    history: list[dict] = Field(default_factory=list)
    partial_profile: dict | None = None


class LayoutFromProfileRequest(BaseModel):
    """Request body for computing layout from a LearnerProfile."""
    preferences: dict = Field(default_factory=dict)
    behavior: dict = Field(default_factory=dict)
    raw_description: str = ""
    confidence: float = 0.5
    learning_goal: str | None = None
    background_level: str = "unknown"


@router.get("/demo-course", summary="Get or create the demo course")
async def get_demo_course(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the demo course ID, seeding it first if needed.

    Used by the setup flow's "Try with sample content" fast path.
    """
    result = await db.execute(
        select(Course).where(Course.name == DEMO_COURSE_NAME)
    )
    course = result.scalar_one_or_none()
    if not course:
        await seed_demo_course(db)
        await db.commit()
        result = await db.execute(
            select(Course).where(Course.name == DEMO_COURSE_NAME)
        )
        course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=500, detail="Failed to create demo course")
    return {"id": str(course.id), "name": course.name}


@router.post("/interview", summary="Onboarding interview turn")
async def interview_turn(
    body: OnboardingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run one turn of the onboarding interview.

    The agent asks 2-3 questions about learning habits, then extracts a
    LearnerProfile and recommends a block layout. Typically 2-4 turns.

    Returns: ``{response, actions, profile, complete}``
    """
    ctx = AgentContext(
        user_id=user.id,
        course_id=_NIL_COURSE_ID,
        user_message=body.message,
        conversation_history=body.history[-10:],
        intent=IntentType.ONBOARDING,
        intent_confidence=1.0,
        phase=TaskPhase.IDLE,
    )
    ctx.metadata["learner_profile"] = body.partial_profile or {}

    try:
        ctx = await _onboarding_agent.execute(ctx, db)
    except (ValueError, KeyError, ConnectionError, OSError, RuntimeError) as exc:
        logger.exception("Onboarding interview error: %s", exc)
        raise HTTPException(status_code=502, detail="Interview agent failed") from exc
    except Exception as exc:
        # Catch LLM provider errors (openai.APIConnectionError, etc.)
        exc_module = getattr(type(exc), "__module__", "")
        if "openai" in exc_module or "anthropic" in exc_module or "httpx" in exc_module:
            logger.exception("Onboarding LLM connection error: %s", exc)
            raise HTTPException(status_code=503, detail="LLM service unavailable") from exc
        raise

    complete = bool(ctx.metadata.get("onboarding_complete"))
    actions: list[dict] = list(ctx.actions)

    if complete:
        profile = LearnerProfile(**ctx.metadata["learner_profile"])
        layout = ctx.metadata.get("recommended_layout") or profile_to_layout(profile)

        # Persist preferences + memory
        await _persist_preferences(db, user, profile)
        if profile.raw_description:
            await encode_memory(
                db,
                user.id,
                None,
                user_message=profile.raw_description,
                assistant_response=(
                    f"Learning profile: {profile.behavior.learning_style} learner, "
                    f"{profile.behavior.study_pattern} study pattern, "
                    f"{profile.behavior.session_duration} sessions"
                ),
            )
        await db.commit()

        # Ensure layout is in actions for frontend
        if not any(a.get("type") == "recommend_layout" for a in actions):
            actions.append({
                "type": "recommend_layout",
                "layout": layout,
                "profile_summary": {
                    "style": profile.behavior.learning_style,
                    "pattern": profile.behavior.study_pattern,
                    "duration": profile.behavior.session_duration,
                },
            })

    return {
        "response": ctx.response,
        "actions": actions,
        "profile": ctx.metadata.get("learner_profile"),
        "complete": complete,
    }


@router.post("/layout-from-profile", summary="Compute layout from learner profile")
async def layout_from_profile(
    body: LayoutFromProfileRequest,
    _user: User = Depends(get_current_user),
) -> dict:
    """Compute the recommended block layout from a LearnerProfile.

    Non-streaming endpoint for re-computing layout without running the
    full interview (e.g., after manual profile edits).
    """
    profile = LearnerProfile(**body.model_dump())
    layout = profile_to_layout(profile)
    return {
        "layout": layout,
        "profile_summary": {
            "style": profile.behavior.learning_style,
            "pattern": profile.behavior.study_pattern,
            "duration": profile.behavior.session_duration,
        },
    }


# ── Helpers ──


async def _persist_preferences(
    db: AsyncSession,
    user: User,
    profile: LearnerProfile,
) -> None:
    """Store extracted profile dimensions as UserPreference rows."""
    pref_dimensions: list[tuple[str, str]] = [
        ("learning_style", profile.behavior.learning_style),
        ("study_pattern", profile.behavior.study_pattern),
        ("session_duration", profile.behavior.session_duration),
        ("content_style", profile.preferences.content_style),
        ("background_level", profile.background_level),
    ]

    # Add boolean preferences
    for attr in [
        "prefers_visual_aids",
        "prefers_note_taking",
        "prefers_active_recall",
        "prefers_spaced_review",
        "prefers_mistake_analysis",
        "prefers_planning",
    ]:
        if getattr(profile.preferences, attr, False):
            pref_dimensions.append((attr, "true"))

    for dim, val in pref_dimensions:
        if val and val != "unknown" and val != "mixed":
            existing = await db.execute(
                select(UserPreference).where(
                    UserPreference.user_id == user.id,
                    UserPreference.dimension == dim,
                )
            )
            pref = existing.scalar_one_or_none()
            if pref:
                pref.value = val
                pref.source = "onboarding_interview"
                pref.confidence = profile.confidence
            else:
                db.add(
                    UserPreference(
                        user_id=user.id,
                        dimension=dim,
                        value=val,
                        scope="global",
                        source="onboarding_interview",
                        confidence=profile.confidence,
                    )
                )
    await db.flush()
