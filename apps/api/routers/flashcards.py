"""Flashcard + FSRS spaced repetition API endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from libs.exceptions import AppError, NotFoundError, reraise_as_app_error
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.llm.readiness import ensure_llm_ready

router = APIRouter()


class GenerateRequest(BaseModel):
    course_id: uuid.UUID
    content_node_id: uuid.UUID | None = None
    count: int = 5
    mode: str | None = None  # learning mode: course_following, self_paced, exam_prep, maintenance


class ReviewRequest(BaseModel):
    card: dict
    rating: int  # 1=Again, 2=Hard, 3=Good, 4=Easy
    batch_id: uuid.UUID | None = None
    card_index: int | None = None


class SaveGeneratedFlashcardsRequest(BaseModel):
    course_id: uuid.UUID
    cards: list[dict]
    title: str | None = None
    replace_batch_id: uuid.UUID | None = None


@router.post("/generate")
async def generate_flashcards(body: GenerateRequest, db: AsyncSession = Depends(get_db)):
    """Generate flashcards from course content using LLM + FSRS."""
    from services.spaced_repetition.flashcards import generate_flashcards

    await ensure_llm_ready("Flashcard generation")
    try:
        cards = await generate_flashcards(
            db, body.course_id, body.content_node_id, body.count, mode=body.mode
        )
    except Exception as exc:
        reraise_as_app_error(exc, "Flashcard generation failed")
    return {"cards": cards, "count": len(cards)}


@router.post("/review")
async def review_flashcard_endpoint(
    body: ReviewRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Review a flashcard and get FSRS scheduling result."""
    from services.spaced_repetition.flashcards import review_flashcard

    updated_card = review_flashcard(body.card, body.rating)

    # Persist FSRS state back to the GeneratedAsset in the database
    if body.batch_id is not None and body.card_index is not None:
        from models.generated_asset import GeneratedAsset

        result = await db.execute(
            select(GeneratedAsset).where(
                GeneratedAsset.batch_id == body.batch_id,
                GeneratedAsset.user_id == user.id,
                GeneratedAsset.is_archived == False,  # noqa: E712
            )
        )
        asset = result.scalar_one_or_none()
        if asset and asset.content:
            cards = asset.content.get("cards", [])
            if 0 <= body.card_index < len(cards):
                cards[body.card_index]["fsrs"] = updated_card.get("fsrs", {})
                # SQLAlchemy needs the JSON column reassigned to detect the mutation
                asset.content = {**asset.content, "cards": cards}

    # Emit standardized learning event for analytics + plugin hooks
    try:
        from services.analytics.events import emit_flashcard_reviewed
        card_id = body.card.get("id") or body.card.get("front", "unknown")[:40]
        course_id = body.card.get("course_id")
        if course_id:
            await emit_flashcard_reviewed(
                db,
                user_id=user.id,
                course_id=uuid.UUID(course_id) if isinstance(course_id, str) else course_id,
                card_id=str(card_id),
                rating=body.rating,
            )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Flashcard learning event emission failed (best-effort)")

    # Single commit covers both the FSRS persistence and the analytics event
    await db.commit()

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
        raise NotFoundError(resource="generated_asset", resource_id=str(body.replace_batch_id)) from exc

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


@router.get("/lector-order/{course_id}")
async def get_lector_ordered_flashcards(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get flashcards ordered by LECTOR semantic priority instead of pure FSRS due date.

    Merges LECTOR concept priority with flashcard content for a semantically-aware review order.
    """
    from models.generated_asset import GeneratedAsset
    from services.lector import get_smart_review_session

    await get_course_or_404(db, course_id, user_id=user.id)

    # Get LECTOR priority order
    review_items = await get_smart_review_session(db, user.id, course_id, max_items=30)
    concept_priority = {item.concept_name.lower(): (i, item) for i, item in enumerate(review_items)}

    # Get all active flashcard batches
    result = await db.execute(
        select(GeneratedAsset).where(
            GeneratedAsset.user_id == user.id,
            GeneratedAsset.course_id == course_id,
            GeneratedAsset.asset_type == "flashcards",
            GeneratedAsset.is_archived == False,  # noqa: E712
        )
    )
    batches = result.scalars().all()

    now = datetime.now(timezone.utc)
    scored_cards: list[tuple[float, int, dict]] = []

    for batch in batches:
        cards = (batch.content or {}).get("cards", [])
        for idx, card in enumerate(cards):
            fsrs = card.get("fsrs")
            is_due = True
            if fsrs and fsrs.get("due"):
                try:
                    due_dt = datetime.fromisoformat(fsrs["due"].replace("Z", "+00:00"))
                    is_due = due_dt <= now
                except (ValueError, TypeError):
                    pass

            if not is_due:
                continue

            # Score by LECTOR concept match
            front = (card.get("front") or "").lower()
            concept = card.get("concept", "").lower()
            priority_score = 999.0  # Default: no concept match
            reason = "due"

            for concept_name, (rank, item) in concept_priority.items():
                if concept_name in front or concept_name in concept or concept in concept_name:
                    priority_score = rank
                    reason = item.reason
                    break

            card_with_meta = {
                **card,
                "batch_id": str(batch.batch_id),
                "card_index": idx,
                "lector_priority": priority_score,
                "lector_reason": reason,
            }
            scored_cards.append((priority_score, idx, card_with_meta))

    scored_cards.sort(key=lambda x: (x[0], x[1]))
    ordered_cards = [c[2] for c in scored_cards]

    return {
        "cards": ordered_cards,
        "count": len(ordered_cards),
        "lector_concepts": len(review_items),
    }


@router.get("/due/{course_id}")
async def get_due_flashcards(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get flashcards due for review today across all saved batches for a course.

    Scans all active flashcard batches and returns cards whose FSRS `due` date
    is at or before the current time, plus any new cards (no FSRS data yet).
    """
    from models.generated_asset import GeneratedAsset

    await get_course_or_404(db, course_id, user_id=user.id)

    result = await db.execute(
        select(GeneratedAsset).where(
            GeneratedAsset.user_id == user.id,
            GeneratedAsset.course_id == course_id,
            GeneratedAsset.asset_type == "flashcards",
            GeneratedAsset.is_archived == False,  # noqa: E712
        )
    )
    batches = result.scalars().all()

    now = datetime.now(timezone.utc)
    due_cards: list[dict] = []

    for batch in batches:
        cards = (batch.content or {}).get("cards", [])
        for card in cards:
            fsrs = card.get("fsrs")
            if not fsrs:
                # New card — always due
                due_cards.append({**card, "batch_id": str(batch.id)})
            else:
                due_str = fsrs.get("due")
                if due_str:
                    try:
                        due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
                        if due_dt <= now:
                            due_cards.append({**card, "batch_id": str(batch.id)})
                    except (ValueError, TypeError):
                        due_cards.append({**card, "batch_id": str(batch.id)})
                else:
                    due_cards.append({**card, "batch_id": str(batch.id)})

    return {"cards": due_cards, "due_count": len(due_cards), "total_batches": len(batches)}
