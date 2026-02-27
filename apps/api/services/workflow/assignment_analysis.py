"""WF-3: Assignment Analysis Workflow.

Flow: load_assignment → extract_requirements → find_relevant_content → generate_guide

Reference from spec:
- WF-3 analyzes uploaded assignments
- Extracts requirements and key topics
- Maps to course content tree
- Generates step-by-step solution guides
"""

import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ingestion import Assignment
from services.llm.router import get_llm_client
from services.search.hybrid import hybrid_search

logger = logging.getLogger(__name__)


ANALYSIS_PROMPT = """Analyze this assignment and provide:

1. **Key Requirements**: List each specific requirement or question
2. **Topics Covered**: List the main concepts/topics tested
3. **Difficulty Assessment**: Rate overall difficulty (easy/medium/hard)
4. **Estimated Time**: How long this should take
5. **Approach Guide**: Step-by-step approach for each requirement

Assignment:
{assignment_text}

Course materials context:
{context}

Be specific and actionable. Reference the course materials where relevant."""


async def load_assignment_content(
    db: AsyncSession,
    assignment_id: uuid.UUID,
) -> Assignment | None:
    """Load an assignment by ID."""
    result = await db.execute(
        select(Assignment).where(Assignment.id == assignment_id)
    )
    return result.scalar_one_or_none()


async def find_relevant_content(
    db: AsyncSession,
    course_id: uuid.UUID,
    assignment_text: str,
) -> list[dict]:
    """Find relevant course content for the assignment using hybrid search."""
    return await hybrid_search(db, course_id, assignment_text, limit=5)


async def run_assignment_analysis(
    db: AsyncSession,
    user_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> dict:
    """Execute WF-3: Assignment analysis workflow.

    Steps:
    1. Load assignment
    2. Find relevant course content
    3. Generate analysis + approach guide
    """
    assignment = await load_assignment_content(db, assignment_id)
    if not assignment:
        return {"error": "Assignment not found"}

    # Find relevant content
    assignment_text = f"{assignment.title}\n{assignment.description or ''}"
    relevant_docs = await find_relevant_content(
        db, assignment.course_id, assignment_text
    )

    context = "\n\n".join(
        f"### {doc['title']}\n{doc['content']}"
        for doc in relevant_docs
    ) or "No relevant course materials found."

    # Generate analysis
    client = get_llm_client()
    analysis, _ = await client.chat(
        "You are a teaching assistant helping students understand assignments.",
        ANALYSIS_PROMPT.format(
            assignment_text=assignment_text,
            context=context,
        ),
    )

    return {
        "assignment_id": str(assignment.id),
        "title": assignment.title,
        "analysis": analysis,
        "relevant_content_count": len(relevant_docs),
    }
