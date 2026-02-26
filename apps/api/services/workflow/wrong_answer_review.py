"""WF-5: Wrong Answer Review Workflow.

Flow: load_wrong_answers → cluster_by_topic → generate_review → update_mastery

Reference from spec:
- WF-5 tracks wrong answers for targeted review
- Clusters mistakes by topic/concept
- Generates focused review materials
- Marks answers as mastered after successful review
"""

import uuid
import logging
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.ingestion import WrongAnswer
from services.llm.router import get_llm_client
from services.search.hybrid import hybrid_search

logger = logging.getLogger(__name__)


async def get_unmastered_wrong_answers(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    limit: int = 20,
) -> list[WrongAnswer]:
    """Get wrong answers that haven't been mastered yet."""
    query = select(WrongAnswer).where(
        WrongAnswer.user_id == user_id,
        WrongAnswer.mastered == False,
    )
    if course_id:
        query = query.where(WrongAnswer.course_id == course_id)

    query = query.order_by(WrongAnswer.created_at.desc()).limit(limit)

    result = await db.execute(query)
    return list(result.scalars().all())


async def generate_review_material(
    db: AsyncSession,
    wrong_answers: list[WrongAnswer],
    course_id: uuid.UUID,
) -> str:
    """Generate targeted review based on wrong answers."""
    if not wrong_answers:
        return "No wrong answers to review. Great job!"

    # Group wrong answers for context
    qa_text = "\n\n".join(
        f"Q: (Problem #{i+1})\n"
        f"Your answer: {wa.user_answer}\n"
        f"Correct answer: {wa.correct_answer or 'Unknown'}\n"
        f"Explanation: {wa.explanation or 'None provided'}"
        for i, wa in enumerate(wrong_answers)
    )

    # Find related content for each wrong answer
    search_query = " ".join(
        (wa.correct_answer or wa.user_answer)[:50]
        for wa in wrong_answers[:5]
    )
    relevant_docs = await hybrid_search(db, course_id, search_query, limit=3)
    context = "\n\n".join(
        f"### {doc['title']}\n{doc['content']}"
        for doc in relevant_docs
    ) or "No specific materials found."

    client = get_llm_client()
    review = await client.chat(
        "You are a patient tutor helping students learn from their mistakes.",
        f"""The student got these questions wrong. Create a focused review session.

## Wrong Answers
{qa_text}

## Relevant Course Materials
{context}

Create a review that:
1. Identifies the common misconceptions or knowledge gaps
2. Explains the correct concepts clearly
3. Provides 2-3 practice problems to test understanding
4. Uses encouraging language

Output in markdown format.""",
    )

    return review


async def mark_as_reviewed(
    db: AsyncSession,
    wrong_answer_ids: list[uuid.UUID],
) -> int:
    """Mark wrong answers as reviewed (increment review count)."""
    count = 0
    for wa_id in wrong_answer_ids:
        result = await db.execute(
            select(WrongAnswer).where(WrongAnswer.id == wa_id)
        )
        wa = result.scalar_one_or_none()
        if wa:
            wa.review_count += 1
            wa.last_reviewed_at = datetime.now(timezone.utc)
            # Auto-master after 3 successful reviews
            if wa.review_count >= 3:
                wa.mastered = True
            count += 1

    return count


async def run_wrong_answer_review(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict:
    """Execute WF-5: Wrong answer review workflow.

    Steps:
    1. Load unmastered wrong answers
    2. Generate targeted review material
    3. Return review content + wrong answer IDs for marking
    """
    wrong_answers = await get_unmastered_wrong_answers(
        db, user_id, course_id
    )

    if not wrong_answers:
        return {
            "review": "All questions mastered! No wrong answers to review.",
            "wrong_answer_count": 0,
            "wrong_answer_ids": [],
        }

    target_course_id = course_id or (wrong_answers[0].course_id if wrong_answers else None)
    if not target_course_id:
        return {"review": "No course context available.", "wrong_answer_count": 0, "wrong_answer_ids": []}

    review = await generate_review_material(db, wrong_answers, target_course_id)

    return {
        "review": review,
        "wrong_answer_count": len(wrong_answers),
        "wrong_answer_ids": [str(wa.id) for wa in wrong_answers],
    }
