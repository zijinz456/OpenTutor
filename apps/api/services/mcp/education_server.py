"""Custom education-focused MCP tools via FastMCP.

Provides high-level learning tools that external AI agents (Claude Desktop,
Cursor, etc.) can invoke to interact with the student's learning state.

These complement the auto-exposed FastAPI routes by offering richer,
agent-friendly interfaces that combine multiple internal services.

Note: In single-user mode, user_id is optional. In multi-user mode, the
caller must provide a user_id to scope queries.
"""

import json
import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

edu_mcp = FastMCP(
    "OpenTutor Education Tools",
    instructions=(
        "A personal learning agent backend. Use these tools to review "
        "flashcards, explain concepts, check study status, search notes, "
        "and get learning recommendations for the student."
    ),
)


# ── Shared helpers ──


def _parse_fsrs_due(fsrs: dict, now: datetime) -> bool:
    """Return True if an FSRS card is due (due date <= now)."""
    due_str = fsrs.get("due", "")
    if not due_str:
        return False
    try:
        due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
        return due_dt <= now
    except (ValueError, TypeError):
        return False


def _escape_like(value: str) -> str:
    """Escape SQL LIKE special characters (%, _) so they match literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _get_first_user_id(db):
    """Fallback: return the first user's ID (single-user deployments)."""
    from sqlalchemy import select
    from models.user import User

    result = await db.execute(select(User.id).limit(1))
    row = result.scalar_one_or_none()
    return row


# ── Tool 1: review_due_cards ──


@edu_mcp.tool()
async def review_due_cards(course_id: Optional[str] = None, user_id: Optional[str] = None) -> str:
    """Get flashcards due for review today.

    Returns a formatted list of due flashcard fronts/backs grouped by course,
    ready for a review session. If course_id is provided, filters to that course.
    """
    from sqlalchemy import select
    from models.generated_asset import GeneratedAsset
    from database import async_session

    async with async_session() as db:
        filters = [
            GeneratedAsset.asset_type == "flashcards",
            GeneratedAsset.is_archived == False,  # noqa: E712
        ]
        if user_id:
            filters.append(GeneratedAsset.user_id == _uuid.UUID(user_id))
        elif uid := await _get_first_user_id(db):
            filters.append(GeneratedAsset.user_id == uid)
        if course_id:
            filters.append(GeneratedAsset.course_id == _uuid.UUID(course_id))

        # Only fetch the two columns we need — avoids loading full ORM objects
        result = await db.execute(
            select(GeneratedAsset.course_id, GeneratedAsset.content)
            .where(*filters)
        )
        rows = result.all()

    now = datetime.now(timezone.utc)
    due_cards = []

    for cid_val, content in rows:
        cards = (content or {}).get("cards", [])
        for card in cards:
            fsrs = card.get("fsrs")
            if not fsrs:
                due_cards.append({
                    "front": card.get("front", ""),
                    "back": card.get("back", ""),
                    "course_id": str(cid_val),
                    "status": "new",
                })
            elif _parse_fsrs_due(fsrs, now):
                due_cards.append({
                    "front": card.get("front", ""),
                    "back": card.get("back", ""),
                    "course_id": str(cid_val),
                    "status": "due",
                })

    if not due_cards:
        return "No flashcards due for review right now. Great job staying on top of reviews!"

    lines = [f"{len(due_cards)} card(s) due for review:\n"]
    for i, card in enumerate(due_cards, 1):
        lines.append(f"{i}. Q: {card['front']}")
        lines.append(f"   A: {card['back']}")
        lines.append(f"   (status: {card['status']})\n")

    return "\n".join(lines)


# ── Tool 2: explain_concept ──


@edu_mcp.tool()
async def explain_concept(concept: str, course_id: str) -> str:
    """Get an explanation of a concept from course materials.

    Searches the course's knowledge graph and content tree to find relevant
    material, then returns a structured explanation with context.
    """
    from sqlalchemy import select
    from models.knowledge_graph import KnowledgePoint
    from models.content import CourseContentTree
    from database import async_session

    cid = _uuid.UUID(course_id)
    escaped = _escape_like(concept)

    async with async_session() as db:
        kg_result = await db.execute(
            select(KnowledgePoint).where(
                KnowledgePoint.course_id == cid,
                KnowledgePoint.label.ilike(f"%{escaped}%"),
            )
        )
        kg_nodes = kg_result.scalars().all()

        ct_result = await db.execute(
            select(CourseContentTree).where(
                CourseContentTree.course_id == cid,
                CourseContentTree.title.ilike(f"%{escaped}%"),
            )
        )
        content_nodes = ct_result.scalars().all()

    parts = []

    if kg_nodes:
        parts.append("Knowledge Graph Entries:")
        for node in kg_nodes[:5]:
            mastery = getattr(node, "mastery", None)
            mastery_str = f" (mastery: {mastery:.0%})" if mastery is not None else ""
            parts.append(f"- {node.label}{mastery_str}")
            if hasattr(node, "description") and node.description:
                parts.append(f"  {node.description}")

    if content_nodes:
        parts.append("\nCourse Content:")
        for node in content_nodes[:5]:
            depth_prefix = "  " * (node.depth if hasattr(node, "depth") else 0)
            parts.append(f"- {depth_prefix}{node.title}")

    if not parts:
        return f"No materials found for '{concept}' in this course. Try a broader search term."

    return f"## {concept}\n\n" + "\n".join(parts)


# ── Tool 3: get_study_status ──


@edu_mcp.tool()
async def get_study_status(course_id: Optional[str] = None, user_id: Optional[str] = None) -> str:
    """Get current study status: progress, due reviews, and active goals.

    Provides an overview of the student's learning state across courses,
    or focused on a specific course if course_id is provided.
    """
    from sqlalchemy import select, func
    from models.progress import LearningProgress
    from models.study_goal import StudyGoal
    from models.course import Course
    from models.generated_asset import GeneratedAsset
    from database import async_session

    async with async_session() as db:
        # Resolve user scope
        uid = _uuid.UUID(user_id) if user_id else await _get_first_user_id(db)

        course_stmt = select(Course)
        if uid:
            course_stmt = course_stmt.where(Course.user_id == uid)
        if course_id:
            course_stmt = course_stmt.where(Course.id == _uuid.UUID(course_id))
        courses = (await db.execute(course_stmt)).scalars().all()

        if not courses:
            return "No courses found. Create a course first to start learning."

        course_ids = [c.id for c in courses[:5]]

        # Batch query 1: progress stats for ALL courses at once
        prog_result = await db.execute(
            select(
                LearningProgress.course_id,
                func.count(LearningProgress.id),
                func.avg(LearningProgress.mastery_score),
            )
            .where(LearningProgress.course_id.in_(course_ids))
            .group_by(LearningProgress.course_id)
        )
        prog_by_course = {
            row[0]: (row[1] or 0, row[2] or 0.0)
            for row in prog_result.all()
        }

        # Batch query 2: flashcard content for ALL courses at once (columns only)
        fc_filters = [
            GeneratedAsset.course_id.in_(course_ids),
            GeneratedAsset.asset_type == "flashcards",
            GeneratedAsset.is_archived == False,  # noqa: E712
        ]
        if uid:
            fc_filters.append(GeneratedAsset.user_id == uid)
        fc_result = await db.execute(
            select(GeneratedAsset.course_id, GeneratedAsset.content)
            .where(*fc_filters)
        )
        fc_rows = fc_result.all()

        now = datetime.now(timezone.utc)
        due_by_course: dict = {}
        for cid_val, content in fc_rows:
            count = 0
            for card in (content or {}).get("cards", []):
                fsrs = card.get("fsrs")
                if not fsrs or _parse_fsrs_due(fsrs, now):
                    count += 1
            due_by_course[cid_val] = due_by_course.get(cid_val, 0) + count

        # Batch query 3: active goals for ALL courses at once
        goals_result = await db.execute(
            select(StudyGoal)
            .where(
                StudyGoal.course_id.in_(course_ids),
                StudyGoal.status == "active",
            )
        )
        all_goals = goals_result.scalars().all()
        goals_by_course: dict = {}
        for g in all_goals:
            goals_by_course.setdefault(g.course_id, []).append(g)

        # Build output
        sections = []
        for course in courses[:5]:
            topic_count, avg_mastery = prog_by_course.get(course.id, (0, 0.0))
            due_count = due_by_course.get(course.id, 0)
            goals = goals_by_course.get(course.id, [])

            section = f"### {course.name}\n"
            section += f"- Topics tracked: {topic_count}\n"
            section += f"- Average mastery: {avg_mastery:.0%}\n"
            section += f"- Cards due for review: {due_count}\n"
            if goals:
                section += f"- Active goals: {', '.join(g.title for g in goals[:3])}\n"
            sections.append(section)

    return "# Study Status\n\n" + "\n".join(sections)


# ── Tool 4: search_notes ──


@edu_mcp.tool()
async def search_notes(query: str, course_id: Optional[str] = None, user_id: Optional[str] = None) -> str:
    """Search through the student's notes.

    Performs keyword search across all notes, optionally filtered by course.
    Returns matching note excerpts with context.
    """
    from sqlalchemy import select
    from models.generated_asset import GeneratedAsset
    from database import async_session

    async with async_session() as db:
        filters = [
            GeneratedAsset.asset_type == "notes",
            GeneratedAsset.is_archived == False,  # noqa: E712
        ]
        if user_id:
            filters.append(GeneratedAsset.user_id == _uuid.UUID(user_id))
        elif uid := await _get_first_user_id(db):
            filters.append(GeneratedAsset.user_id == uid)
        if course_id:
            filters.append(GeneratedAsset.course_id == _uuid.UUID(course_id))

        result = await db.execute(select(GeneratedAsset).where(*filters))
        notes = result.scalars().all()

    query_lower = query.lower()
    matches = []

    for note in notes:
        content = note.content or {}
        text = json.dumps(content) if isinstance(content, dict) else str(content)
        if query_lower in text.lower():
            idx = text.lower().index(query_lower)
            start = max(0, idx - 100)
            end = min(len(text), idx + len(query) + 200)
            snippet = text[start:end]
            if start > 0:
                snippet = "..." + snippet
            if end < len(text):
                snippet = snippet + "..."
            matches.append({
                "title": content.get("title", "Untitled") if isinstance(content, dict) else "Untitled",
                "snippet": snippet,
            })

    if not matches:
        return f"No notes found matching '{query}'."

    lines = [f"Found {len(matches)} note(s) matching '{query}':\n"]
    for m in matches[:10]:
        lines.append(f"**{m['title']}**")
        lines.append(f"> {m['snippet']}\n")

    return "\n".join(lines)


# ── Tool 5: get_learning_recommendations ──


@edu_mcp.tool()
async def get_learning_recommendations(course_id: str) -> str:
    """Get personalized learning recommendations for a course.

    Analyzes the student's progress, weak areas, and due reviews to suggest
    what to study next.
    """
    from sqlalchemy import select
    from models.progress import LearningProgress
    from models.content import CourseContentTree
    from database import async_session

    cid = _uuid.UUID(course_id)

    async with async_session() as db:
        result = await db.execute(
            select(LearningProgress, CourseContentTree.title)
            .outerjoin(
                CourseContentTree,
                LearningProgress.content_node_id == CourseContentTree.id,
            )
            .where(LearningProgress.course_id == cid)
            .order_by(LearningProgress.mastery_score.asc())
        )
        rows = result.all()

    if not rows:
        return "No progress data yet. Start by exploring course materials to get personalized recommendations."

    weak_topics = []
    strong_topics = []

    for progress, title in rows:
        topic_name = title or "Unknown topic"
        entry = {
            "topic": topic_name,
            "mastery": progress.mastery_score,
            "gap_type": progress.gap_type,
        }
        if progress.mastery_score < 0.5:
            weak_topics.append(entry)
        elif progress.mastery_score >= 0.8:
            strong_topics.append(entry)

    parts = ["# Learning Recommendations\n"]

    if weak_topics:
        parts.append("## Priority: Weak Areas")
        for t in weak_topics[:5]:
            gap_info = f" ({t['gap_type']})" if t["gap_type"] else ""
            parts.append(f"- {t['topic']}: {t['mastery']:.0%} mastery{gap_info}")
        parts.append("")

    if strong_topics:
        parts.append("## Strengths")
        for t in strong_topics[:5]:
            parts.append(f"- {t['topic']}: {t['mastery']:.0%} mastery")
        parts.append("")

    avg_mastery = sum(p.mastery_score for p, _ in rows) / len(rows) if rows else 0
    parts.append(f"\nOverall mastery: {avg_mastery:.0%} across {len(rows)} topics")

    return "\n".join(parts)
