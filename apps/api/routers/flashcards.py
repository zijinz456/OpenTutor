"""Flashcard + FSRS spaced repetition API endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

router = APIRouter()


class GenerateRequest(BaseModel):
    course_id: uuid.UUID
    content_node_id: uuid.UUID | None = None
    count: int = 10


class ReviewRequest(BaseModel):
    card: dict
    rating: int  # 1=Again, 2=Hard, 3=Good, 4=Easy


class SaveGeneratedFlashcardsRequest(BaseModel):
    course_id: uuid.UUID
    cards: list[dict]
    title: str | None = None
    replace_batch_id: uuid.UUID | None = None


@router.post("/generate")
async def generate_flashcards(body: GenerateRequest, db: AsyncSession = Depends(get_db)):
    """Generate flashcards from course content using LLM + FSRS."""
    from services.spaced_repetition.flashcards import generate_flashcards

    cards = await generate_flashcards(
        db, body.course_id, body.content_node_id, body.count
    )
    return {"cards": cards, "count": len(cards)}


@router.post("/review")
async def review_flashcard(body: ReviewRequest):
    """Review a flashcard and get FSRS scheduling result."""
    from services.spaced_repetition.flashcards import review_flashcard

    updated_card = review_flashcard(body.card, body.rating)
    return {
        "card": updated_card,
        "next_review": updated_card.get("fsrs", {}).get("due"),
    }


@router.post("/generated/save")
async def save_generated_flashcards(
    body: SaveGeneratedFlashcardsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    course = await get_course_or_404(db, body.course_id, user_id=user.id)

    from services.generated_assets import save_generated_asset

    try:
        result = await save_generated_asset(
            db,
            user_id=user.id,
            course_id=body.course_id,
            asset_type="flashcards",
            title=body.title or course.name,
            content={"cards": body.cards},
            metadata={"count": len(body.cards)},
            replace_batch_id=body.replace_batch_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await db.commit()
    return result


@router.get("/generated/{course_id}")
async def list_generated_flashcards(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_course_or_404(db, course_id, user_id=user.id)

    from services.generated_assets import list_generated_asset_batches

    return await list_generated_asset_batches(
        db,
        user_id=user.id,
        course_id=course_id,
        asset_type="flashcards",
    )
