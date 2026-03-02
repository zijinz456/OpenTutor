"""Anki .apkg export from GeneratedAsset flashcards.

Uses genanki to produce importable Anki decks. The exported deck contains all
non-archived flashcards for a given course, tagged with the course name.
"""

import hashlib
import logging
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _stable_id(seed: str) -> int:
    """Generate a stable integer ID from a string seed (for genanki model/deck IDs)."""
    return int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)


async def export_flashcards_to_anki(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    batch_id: uuid.UUID | None = None,
) -> Path:
    """Export flashcards for a course as an Anki .apkg file.

    Returns the path to a temporary .apkg file. Caller is responsible for cleanup.
    """
    import genanki

    from models.generated_asset import GeneratedAsset
    from models.course import Course

    # Get course name for deck title and tags
    course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one_or_none()
    course_name = course.name if course else "OpenTutor"

    # Fetch flashcard batches
    stmt = select(GeneratedAsset).where(
        GeneratedAsset.user_id == user_id,
        GeneratedAsset.course_id == course_id,
        GeneratedAsset.asset_type == "flashcards",
        GeneratedAsset.is_archived == False,  # noqa: E712
    )
    if batch_id:
        stmt = stmt.where(GeneratedAsset.batch_id == batch_id)

    result = await db.execute(stmt)
    batches = result.scalars().all()

    # Build genanki model with stable IDs
    model_id = _stable_id(f"opentutor-model-{course_id}")
    deck_id = _stable_id(f"opentutor-deck-{course_id}")

    model = genanki.Model(
        model_id,
        "OpenTutor Card",
        fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": '{{FrontSide}}<hr id="answer">{{Back}}',
            }
        ],
    )

    deck = genanki.Deck(deck_id, f"OpenTutor - {course_name}")
    tag = course_name.replace(" ", "_")

    card_count = 0
    for batch in batches:
        cards = (batch.content or {}).get("cards", [])
        for card in cards:
            front = card.get("front", "").strip()
            back = card.get("back", "").strip()
            if front and back:
                note = genanki.Note(model=model, fields=[front, back], tags=[tag])
                deck.add_note(note)
                card_count += 1

    if card_count == 0:
        raise ValueError("No flashcards found to export.")

    # Write to temp file
    tmp = tempfile.NamedTemporaryFile(suffix=".apkg", delete=False)
    tmp_path = Path(tmp.name)
    try:
        tmp.close()
        genanki.Package(deck).write_to_file(str(tmp_path))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    logger.info("Exported %d flashcards to Anki for course %s", card_count, course_id)
    return tmp_path
