"""Progress tracking + learning template API endpoints."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth.dependency import get_current_user

router = APIRouter()


class ApplyTemplateRequest(BaseModel):
    template_id: uuid.UUID
    course_id: uuid.UUID | None = None


# ── Progress Endpoints ──


@router.get("/courses/{course_id}")
async def get_course_progress(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get learning progress overview for a course."""
    from services.progress.tracker import get_course_progress

    return await get_course_progress(db, user.id, course_id)


# ── Template Endpoints ──


@router.get("/templates")
async def list_templates(db: AsyncSession = Depends(get_db)):
    """List all available learning templates."""
    from services.templates.system import list_templates

    return await list_templates(db)


@router.post("/templates/apply")
async def apply_template(
    body: ApplyTemplateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply a learning template to the user's preferences."""
    from services.templates.system import apply_template

    result = await apply_template(db, user.id, body.template_id, body.course_id)
    await db.commit()
    return result


@router.post("/templates/seed")
async def seed_templates(db: AsyncSession = Depends(get_db)):
    """Seed built-in learning templates (run once on setup)."""
    from services.templates.system import seed_builtin_templates

    count = await seed_builtin_templates(db)
    await db.commit()
    return {"seeded": count}


# ── Knowledge Graph Endpoint ──


@router.get("/courses/{course_id}/knowledge-graph")
async def get_knowledge_graph(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get knowledge graph for a course (D3-compatible format)."""
    from services.knowledge.graph import build_knowledge_graph

    return await build_knowledge_graph(db, course_id, user.id)
