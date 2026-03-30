"""Review-related signal collectors.

Covers: weak areas, content staleness, layout adaptation.
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models.ingestion import WrongAnswer

from ._types import AgendaSignal

logger = logging.getLogger(__name__)


async def _collect_weak_areas(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Courses with >=3 unmastered wrong answers."""
    query = (
        select(WrongAnswer.course_id, func.count(WrongAnswer.id).label("cnt"))
        .where(WrongAnswer.user_id == user_id, WrongAnswer.mastered.is_(False))
    )
    if course_id:
        query = query.where(WrongAnswer.course_id == course_id)
    query = query.group_by(WrongAnswer.course_id)
    result = await db.execute(query)

    signals: list[AgendaSignal] = []
    for cid, cnt in result.all():
        if cnt < 3:
            continue
        signals.append(AgendaSignal(
            signal_type="weak_area",
            user_id=user_id,
            course_id=cid,
            entity_id=f"weak:{cid}",
            title=f"{cnt} unmastered wrong answers",
            urgency=min(55.0 + cnt * 2, 75.0),
            detail={"unmastered_count": cnt},
        ))
    return signals


async def _collect_content_stale(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Content stale signal -- disabled (ContentMutation model removed)."""
    return []


async def _collect_layout_adaptation(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Suggest layout changes based on cognitive load, error patterns, and confusion pairs.

    Fires when:
    - Cognitive load has been high for 3+ consecutive messages -> simplify layout
    - Error pattern concentrated in one category -> surface targeted review
    - Confusion pairs detected -> suggest review mode
    """
    if not course_id:
        return []

    signals: list[AgendaSignal] = []

    # Check consecutive high cognitive load -> simplify layout
    try:
        from services.agent.kv_store import kv_get
        cl_state = await kv_get(db, user_id, "cognitive_load", "consecutive", course_id=course_id)
        if isinstance(cl_state, dict) and cl_state.get("consecutive_high", 0) >= 3:
            signals.append(AgendaSignal(
                signal_type="layout_adaptation",
                user_id=user_id,
                course_id=course_id,
                entity_id="layout:simplify",
                title="High cognitive load -- simplify layout",
                urgency=70.0,
                detail={
                    "action": "simplify_layout",
                    "consecutive_high": cl_state["consecutive_high"],
                    "suggestion": "Hide non-essential blocks (forecast, agent_insight, knowledge_graph) to reduce visual clutter",
                },
            ))
    except (SQLAlchemyError, ImportError, ConnectionError, TimeoutError):
        logger.debug("Cognitive load KV lookup failed in layout adaptation", exc_info=True)

    # Check for confusion pairs -> suggest review
    try:
        from services.loom_confusion import get_confused_concepts
        pairs = await get_confused_concepts(db, course_id)
        if len(pairs) >= 2:
            signals.append(AgendaSignal(
                signal_type="layout_adaptation",
                user_id=user_id,
                course_id=course_id,
                entity_id="layout:confusion_review",
                title=f"{len(pairs)} confused concept pairs -- review recommended",
                urgency=55.0,
                detail={
                    "action": "add_block",
                    "block_type": "wrong_answers",
                    "confused_pairs": [[p["concept_a"], p["concept_b"]] for p in pairs],
                    "suggestion": "Surface wrong_answers block and switch to review tab",
                },
            ))
    except (SQLAlchemyError, ImportError, ConnectionError, TimeoutError):
        logger.debug("Confusion pair lookup failed in layout adaptation", exc_info=True)

    # Check for recurring error patterns -> surface wrong_answers
    try:
        wa_count_result = await db.execute(
            select(func.count(WrongAnswer.id)).where(
                WrongAnswer.user_id == user_id,
                WrongAnswer.course_id == course_id,
                WrongAnswer.mastered == False,  # noqa: E712
            )
        )
        unmastered = wa_count_result.scalar() or 0
        if unmastered >= 5:
            cat_result = await db.execute(
                select(WrongAnswer.error_category, func.count(WrongAnswer.id).label("cnt"))
                .where(
                    WrongAnswer.user_id == user_id,
                    WrongAnswer.course_id == course_id,
                    WrongAnswer.mastered == False,  # noqa: E712
                    WrongAnswer.error_category.isnot(None),
                )
                .group_by(WrongAnswer.error_category)
                .order_by(func.count(WrongAnswer.id).desc())
                .limit(1)
            )
            top_cat = cat_result.one_or_none()
            if top_cat and top_cat[1] >= 3:
                signals.append(AgendaSignal(
                    signal_type="layout_adaptation",
                    user_id=user_id,
                    course_id=course_id,
                    entity_id=f"layout:error_pattern:{top_cat[0]}",
                    title=f"Recurring {top_cat[0]} errors ({top_cat[1]}x) -- targeted review needed",
                    urgency=60.0,
                    detail={
                        "action": "focus_error_pattern",
                        "error_category": top_cat[0],
                        "count": top_cat[1],
                        "suggestion": f"Focus review on {top_cat[0]} errors with diagnostic pairs",
                    },
                ))
    except (SQLAlchemyError, ConnectionError, TimeoutError):
        logger.debug("Error pattern query failed in layout adaptation", exc_info=True)

    return signals
