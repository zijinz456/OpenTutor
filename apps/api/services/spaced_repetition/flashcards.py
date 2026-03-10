"""Flashcard generation service.

Auto-generates flashcards from course content using LLM.
Reference: spaceforge — 6-provider AI flashcard generation pattern.
"""

import uuid
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.content import CourseContentTree
from models.progress import LearningProgress
from services.llm.router import get_llm_client
from services.spaced_repetition.fsrs import FSRSCard, review_card

logger = logging.getLogger(__name__)

FLASHCARD_PROMPT = """Generate flashcards from this educational content.

Content:
{content}

Create {count} flashcards. Each flashcard should have:
- A clear, specific question (front)
- A concise, accurate answer (back)
- A difficulty tag: easy, medium, or hard

Output as JSON array:
[
  {{"front": "question", "back": "answer", "difficulty": "medium"}},
  ...
]

Rules:
- Focus on key concepts and definitions
- Avoid trivial questions
- Make questions specific enough to have one clear answer
- Include a mix of recall, understanding, and application questions"""

_MODE_FLASHCARD_HINTS: dict[str, str] = {
    "exam_prep": "\nMode: EXAM PREP — Prefer cloze-deletion style and application questions. Bias toward harder difficulty.",
    "maintenance": "\nMode: MAINTENANCE — Only cover previously-seen core concepts. Focus on retention, not new material.",
    "self_paced": "\nMode: SELF-PACED — Include exploratory, open-ended questions. Encourage cross-topic connections.",
    "course_following": "\nMode: COURSE FOLLOWING — Follow the syllabus order. Only test concepts from the provided content.",
}


async def generate_flashcards(
    db: AsyncSession,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None = None,
    count: int = 5,
    mode: str | None = None,
) -> list[dict]:
    """Generate flashcards from course content using LLM.

    If content_node_id is provided, generates from that specific node.
    Otherwise, generates from the most recent content.
    """
    # Get content
    if content_node_id:
        result = await db.execute(
            select(CourseContentTree).where(CourseContentTree.id == content_node_id)
        )
        nodes = [result.scalar_one_or_none()]
        nodes = [n for n in nodes if n]
    else:
        result = await db.execute(
            select(CourseContentTree)
            .where(CourseContentTree.course_id == course_id)
            .order_by(CourseContentTree.created_at.desc())
            .limit(5)
        )
        nodes = list(result.scalars().all())

    if not nodes:
        return []

    content = "\n\n".join(
        f"## {n.title}\n{n.content or ''}"
        for n in nodes
    )[:5000]  # Limit context size

    client = get_llm_client()
    prompt = FLASHCARD_PROMPT.format(content=content, count=count)
    if mode and mode in _MODE_FLASHCARD_HINTS:
        prompt += _MODE_FLASHCARD_HINTS[mode]
    response, _ = await client.chat(
        "You are an expert at creating educational flashcards. Output only valid JSON.",
        prompt,
    )

    # Parse response
    from libs.text_utils import parse_llm_json

    flashcards = parse_llm_json(response, default=[])
    if not isinstance(flashcards, list):
        logger.warning("Failed to parse flashcard JSON, returning empty")
        flashcards = []

    # Add metadata
    for i, card in enumerate(flashcards):
        card["id"] = str(uuid.uuid4())
        card["course_id"] = str(course_id)
        card["fsrs"] = {
            "difficulty": 5.0,
            "stability": 0.0,
            "reps": 0,
            "lapses": 0,
            "state": "new",
            "due": None,
        }

    return flashcards


def review_flashcard(card_data: dict, rating: int) -> dict:
    """Process a flashcard review using FSRS algorithm.

    rating: 1=Again, 2=Hard, 3=Good, 4=Easy
    Returns updated card data with next review date.
    """
    fsrs_data = card_data.get("fsrs", {})

    card = FSRSCard(
        difficulty=fsrs_data.get("difficulty", 5.0),
        stability=fsrs_data.get("stability", 0.0),
        reps=fsrs_data.get("reps", 0),
        lapses=fsrs_data.get("lapses", 0),
        state=fsrs_data.get("state", "new"),
        last_review=datetime.fromisoformat(fsrs_data["last_review"]) if fsrs_data.get("last_review") else None,
    )

    card, log = review_card(card, rating)

    card_data["fsrs"] = {
        "difficulty": card.difficulty,
        "stability": card.stability,
        "reps": card.reps,
        "lapses": card.lapses,
        "state": card.state,
        "last_review": card.last_review.isoformat() if card.last_review else None,
        "due": card.due.isoformat() if card.due else None,
    }

    return card_data
