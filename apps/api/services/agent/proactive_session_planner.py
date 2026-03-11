"""Proactive Session Planner — system-initiated learning based on Bloom's 2σ.

Instead of waiting for students to ask questions, this module determines
when the system should proactively initiate a guided learning session.

Decision criteria (inspired by Bloom's mastery learning research):
- Inactivity: student hasn't studied for ≥2 days
- Forgetting risk: ≥3 concepts at risk (LECTOR urgent)
- Mastery regression: average mastery dropped since last session
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class SessionOffer:
    """A proactive session offer to present to the student."""

    should_initiate: bool
    reason: str
    session_type: str  # "review" | "new_material" | "mixed"
    topic: str | None = None
    concepts_at_risk: list[str] | None = None
    resumption_prompt: str | None = None


async def evaluate_proactive_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> SessionOffer:
    """Evaluate whether the system should proactively offer a learning session.

    Called on course page load via the agenda system.
    """
    from services.memory.pipeline import generate_teaching_state, format_resumption_prompt

    state = await generate_teaching_state(db, user_id, course_id)
    if not state:
        return SessionOffer(
            should_initiate=False,
            reason="No knowledge graph available yet",
            session_type="new_material",
        )

    days_since = state.get("days_since_last_session")
    urgency = state.get("review_urgency", 0)
    weaknesses = state.get("weaknesses", [])
    next_topic = state.get("next_topic")
    resumption = format_resumption_prompt(state)

    # Decision 1: High forgetting risk — prioritize review
    if urgency >= 3:
        return SessionOffer(
            should_initiate=True,
            reason=f"{urgency} concepts at risk of being forgotten",
            session_type="review",
            concepts_at_risk=state.get("weaknesses", [])[:5],
            resumption_prompt=resumption,
        )

    # Decision 2: Extended inactivity — re-engage with mixed session
    if days_since is not None and days_since >= 2:
        session_type = "review" if urgency >= 1 else "mixed"
        return SessionOffer(
            should_initiate=True,
            reason=f"Haven't studied in {days_since} days",
            session_type=session_type,
            topic=next_topic,
            concepts_at_risk=weaknesses[:3] if weaknesses else None,
            resumption_prompt=resumption,
        )

    # Decision 3: Many weak areas — suggest targeted practice
    if len(weaknesses) >= 3:
        return SessionOffer(
            should_initiate=True,
            reason=f"{len(weaknesses)} concepts need work",
            session_type="new_material",
            topic=next_topic,
            resumption_prompt=resumption,
        )

    # No proactive session needed
    return SessionOffer(
        should_initiate=False,
        reason="On track — no proactive session needed",
        session_type="new_material",
        topic=next_topic,
    )
