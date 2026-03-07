"""Knowledge graph API endpoints.

Provides D3-compatible node-link graph data for visualization,
confusion pair detection, and learning path generation.
"""

import uuid
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge-graph", tags=["knowledge-graph"])


@router.get("/courses/{course_id}")
async def get_knowledge_graph(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full knowledge graph for a course with mastery coloring.

    D3-compatible node-link format with Bloom levels and confusion pairs.
    """
    await get_course_or_404(db, course_id, user_id=user.id)

    from services.loom import get_mastery_graph
    graph = await get_mastery_graph(db, user.id, course_id)
    return graph


@router.get("/courses/{course_id}/learning-path")
async def get_learning_path(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recommended study order using topological sort with Bloom level ordering."""
    await get_course_or_404(db, course_id, user_id=user.id)

    from services.loom import generate_learning_path
    path = await generate_learning_path(db, course_id, user.id)
    return {"path": path}


@router.get("/courses/{course_id}/prerequisite-gaps")
async def get_prerequisite_gaps(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Find unmastered prerequisites that may be blocking progress."""
    await get_course_or_404(db, course_id, user_id=user.id)

    from services.loom import check_prerequisite_gaps
    gaps = await check_prerequisite_gaps(db, user.id, course_id)
    return {"gaps": gaps}


@router.post("/courses/{course_id}/detect-confusion")
async def detect_confusion(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Analyze wrong answers to detect concept confusion pairs."""
    await get_course_or_404(db, course_id, user_id=user.id)

    from services.loom_confusion import detect_confusion_pairs
    pairs = await detect_confusion_pairs(db, course_id, user_id=user.id)
    await db.commit()
    return {"confusion_pairs": pairs, "count": len(pairs)}


@router.get("/courses/{course_id}/confused-concepts")
async def get_confused_concepts(
    course_id: uuid.UUID,
    concept: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get known confusion pairs for a course or specific concept."""
    await get_course_or_404(db, course_id, user_id=user.id)

    from services.loom_confusion import get_confused_concepts as _get
    pairs = await _get(db, course_id, concept_name=concept)
    return {"pairs": pairs}
