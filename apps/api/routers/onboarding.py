"""Onboarding interview endpoint — SSE streaming + preference persistence.

Lightweight chat for the habit interview — bypasses full orchestrator
(no RAG, no block decisions, no course context needed).

Streams responses via SSE, extracts LearnerProfile, persists preferences
and memories when onboarding completes.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from database import get_db
from models.preference import UserPreference
from models.user import User
from schemas.learner_profile import LearnerProfile
from services.agent.agents.onboarding import OnboardingAgent
from services.agent.state import AgentContext, IntentType, TaskPhase
from services.auth.dependency import get_current_user
from services.block_decision.profile_mapper import profile_to_layout
from services.memory.pipeline import encode_memory

logger = logging.getLogger(__name__)
router = APIRouter()

_onboarding_agent = OnboardingAgent()


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


@router.post("/interview", summary="Onboarding interview turn (SSE streaming)")
async def interview_stream(
    body: OnboardingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream one turn of the onboarding interview via SSE.

    The agent asks 2-3 questions about learning habits, then extracts a
    LearnerProfile and recommends a block layout. Typically 2-4 turns.

    SSE events:
    - ``message``: text chunk from the agent
    - ``done``: final event with profile/layout data (if onboarding complete)
    - ``error``: on failure
    """
    ctx = AgentContext(
        user_id=user.id,
        course_id=uuid.UUID(int=0),
        user_message=body.message,
        conversation_history=body.history[-10:],
        intent=IntentType.ONBOARDING,
        intent_confidence=1.0,
        phase=TaskPhase.IDLE,
    )
    ctx.metadata["learner_profile"] = body.partial_profile or {}

    async def event_generator():
        try:
            async for chunk in _onboarding_agent.stream(ctx, db):
                yield {
                    "event": "message",
                    "data": json.dumps({"content": chunk}),
                }

            # After streaming completes, check if onboarding is done
            if ctx.metadata.get("onboarding_complete"):
                profile = LearnerProfile(**ctx.metadata["learner_profile"])
                layout = ctx.metadata.get("recommended_layout") or profile_to_layout(profile)

                # ── Persist preferences ──
                await _persist_preferences(db, user, profile)

                # ── Persist memory ──
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

                yield {
                    "event": "done",
                    "data": json.dumps({
                        "onboarding_complete": True,
                        "layout": layout,
                        "profile_summary": {
                            "style": profile.behavior.learning_style,
                            "pattern": profile.behavior.study_pattern,
                            "duration": profile.behavior.session_duration,
                        },
                    }),
                }
            else:
                # Interview still in progress — send done with partial state
                yield {
                    "event": "done",
                    "data": json.dumps({
                        "onboarding_complete": False,
                        "partial_profile": ctx.metadata.get("learner_profile"),
                    }),
                }

        except (ValueError, KeyError, ConnectionError, OSError, RuntimeError) as exc:
            logger.exception("Onboarding interview error: %s", exc)
            yield {
                "event": "error",
                "data": json.dumps({"error": "An error occurred during the interview. Please try again."}),
            }

    return EventSourceResponse(event_generator())


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
