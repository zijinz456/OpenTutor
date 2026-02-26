"""Flashcard + FSRS spaced repetition API endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db

router = APIRouter()


class GenerateRequest(BaseModel):
    course_id: uuid.UUID
    content_node_id: uuid.UUID | None = None
    count: int = 10


class ReviewRequest(BaseModel):
    card: dict
    rating: int  # 1=Again, 2=Hard, 3=Good, 4=Easy


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
