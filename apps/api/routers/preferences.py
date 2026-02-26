"""Preference CRUD and cascade resolution endpoints."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.preference import UserPreference
from routers.courses import get_or_create_user
from schemas.preference import PreferenceCreate, PreferenceResponse, ResolvedPreferences
from services.preference.engine import resolve_preferences

router = APIRouter()


@router.get("/", response_model=list[PreferenceResponse])
async def list_preferences(
    scope: str | None = None,
    course_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    user = await get_or_create_user(db)
    query = select(UserPreference).where(UserPreference.user_id == user.id)
    if scope:
        query = query.where(UserPreference.scope == scope)
    if course_id:
        query = query.where(UserPreference.course_id == course_id)
    result = await db.execute(query.order_by(UserPreference.updated_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=PreferenceResponse, status_code=201)
async def set_preference(body: PreferenceCreate, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db)

    # Upsert: check if same dimension+scope+course exists
    query = select(UserPreference).where(
        UserPreference.user_id == user.id,
        UserPreference.dimension == body.dimension,
        UserPreference.scope == body.scope,
    )
    if body.course_id:
        query = query.where(UserPreference.course_id == body.course_id)
    else:
        query = query.where(UserPreference.course_id.is_(None))

    result = await db.execute(query)
    existing = result.scalar_one_or_none()

    if existing:
        existing.value = body.value
        existing.source = body.source
        existing.confidence = 0.7 if body.source == "onboarding" else 0.5
    else:
        pref = UserPreference(
            user_id=user.id,
            course_id=body.course_id,
            dimension=body.dimension,
            value=body.value,
            scope=body.scope,
            source=body.source,
            confidence=0.7 if body.source == "onboarding" else 0.5,
        )
        db.add(pref)
        existing = pref

    await db.commit()
    await db.refresh(existing)
    return existing


@router.get("/resolve", response_model=ResolvedPreferences)
async def resolve(
    course_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Resolve all preferences using the 3-layer cascade."""
    user = await get_or_create_user(db)
    return await resolve_preferences(db, user.id, course_id)
