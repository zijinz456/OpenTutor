"""Canvas LMS HTML parser — extracts courses and assignments from Canvas pages.

This module is an optional parser utility for Canvas-like pages. The main
scheduled scraping pipeline stays generic; callers can invoke these helpers when
they need structured extraction from Canvas HTML.

Supported Canvas page types (auto-detected from URL path):
- /courses                → course list
- /courses/{id}           → single course home
- /courses/{id}/assignments → assignment list
- /courses/{id}/syllabus  → syllabus content → ingestion pipeline
- /dashboard              → dashboard with course cards
"""

import logging
import re
import uuid
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.ingestion import Assignment

logger = logging.getLogger(__name__)


def detect_canvas_page_type(url: str) -> str:
    """Detect what kind of Canvas page this URL points to."""
    path = url.rstrip("/").lower()

    if re.search(r"/courses/\d+/assignments", path):
        return "assignments"
    if re.search(r"/courses/\d+/syllabus", path):
        return "syllabus"
    if re.search(r"/courses/\d+", path):
        return "course_home"
    if path.endswith("/courses"):
        return "course_list"
    if "/dashboard" in path:
        return "dashboard"
    return "unknown"


async def parse_canvas_html(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    url: str,
    html: str,
) -> dict:
    """Parse Canvas HTML and extract structured data into DB.

    Returns a summary dict with counts of created/updated records.
    """
    page_type = detect_canvas_page_type(url)
    soup = BeautifulSoup(html, "lxml")

    result = {
        "page_type": page_type,
        "courses_created": 0,
        "courses_updated": 0,
        "assignments_created": 0,
        "assignments_updated": 0,
    }

    if page_type == "dashboard":
        created, updated = await _parse_dashboard(db, user_id, soup)
        result["courses_created"] = created
        result["courses_updated"] = updated
    elif page_type == "course_list":
        created, updated = await _parse_course_list(db, user_id, soup)
        result["courses_created"] = created
        result["courses_updated"] = updated
    elif page_type == "assignments":
        created, updated = await _parse_assignments(db, user_id, course_id, soup)
        result["assignments_created"] = created
        result["assignments_updated"] = updated
    elif page_type == "course_home":
        created, updated = await _parse_course_home(db, user_id, course_id, soup)
        result["assignments_created"] = created
        result["assignments_updated"] = updated
    # syllabus and unknown types return empty — caller falls back to generic pipeline

    return result


async def _parse_dashboard(
    db: AsyncSession, user_id: uuid.UUID, soup: BeautifulSoup
) -> tuple[int, int]:
    """Extract courses from Canvas dashboard page."""
    created = 0
    updated = 0

    # Canvas dashboard shows course cards in .ic-DashboardCard
    cards = soup.select(".ic-DashboardCard, .ic-DashboardCard__header")
    for card in cards:
        # Course name is in the card header link or title
        name_el = card.select_one(
            ".ic-DashboardCard__header-title, .ic-DashboardCard__link span"
        )
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        if not name:
            continue

        # Course code (subtitle)
        code_el = card.select_one(".ic-DashboardCard__header-subtitle")
        code = code_el.get_text(strip=True) if code_el else ""

        status = await _upsert_course(db, user_id, name, code)
        if status == "created":
            created += 1
        elif status == "updated":
            updated += 1

    # Fallback: newer Canvas UI uses different selectors
    if not cards:
        card_links = soup.select("[data-testid='k5-course-card'] a, .ic-DashboardCard a")
        for link in card_links:
            name = link.get_text(strip=True)
            if name and len(name) > 2:
                status = await _upsert_course(db, user_id, name, "")
                if status == "created":
                    created += 1
                elif status == "updated":
                    updated += 1

    return created, updated


async def _parse_course_list(
    db: AsyncSession, user_id: uuid.UUID, soup: BeautifulSoup
) -> tuple[int, int]:
    """Extract courses from /courses page."""
    created = 0
    updated = 0

    # Canvas course listing table rows
    rows = soup.select("tr.course-list-table-row, .course-list-course-title-column a")
    for row in rows:
        if row.name == "a":
            name = row.get_text(strip=True)
        else:
            name_el = row.select_one(".course-list-course-title-column a, td:first-child a")
            name = name_el.get_text(strip=True) if name_el else ""

        if not name:
            continue

        status = await _upsert_course(db, user_id, name, "")
        if status == "created":
            created += 1
        elif status == "updated":
            updated += 1

    return created, updated


async def _parse_assignments(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    soup: BeautifulSoup,
) -> tuple[int, int]:
    """Extract assignments from /courses/{id}/assignments page."""
    created = 0
    updated = 0

    # Canvas assignment list items
    items = soup.select(".ig-row, .assignment, li.assignment")
    for item in items:
        title_el = item.select_one(
            ".ig-title a, .assignment-name a, .title a"
        )
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue

        # Try to extract due date
        due_el = item.select_one(".assignment-date-due, .due_date_display, .dateAvailable")
        due_date = _parse_date_text(due_el.get_text(strip=True)) if due_el else None

        # Try to extract points
        points_el = item.select_one(".points_possible, .score-display")
        points = points_el.get_text(strip=True) if points_el else None

        status = await _upsert_assignment(
            db, course_id, title, due_date=due_date,
            metadata={"points": points} if points else None,
        )
        if status == "created":
            created += 1
        elif status == "updated":
            updated += 1

    return created, updated


async def _parse_course_home(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    soup: BeautifulSoup,
) -> tuple[int, int]:
    """Extract upcoming assignments from course home page sidebar."""
    created = 0
    updated = 0

    # Canvas course home shows upcoming items in the sidebar
    upcoming = soup.select(".coming_up .event, .todo-list-item, .planner-item")
    for item in upcoming:
        title_el = item.select_one("a, .todo-list-item-title, .planner-item__title")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue

        due_el = item.select_one(".event-date, .todo-list-item-due, time")
        due_date = None
        if due_el:
            date_str = due_el.get("datetime") or due_el.get_text(strip=True)
            due_date = _parse_date_text(date_str)

        status = await _upsert_assignment(db, course_id, title, due_date=due_date)
        if status == "created":
            created += 1
        elif status == "updated":
            updated += 1

    return created, updated


async def _upsert_course(
    db: AsyncSession, user_id: uuid.UUID, name: str, description: str
) -> str:
    """Create/update course from Canvas scrape.

    Returns one of: "created", "updated", "unchanged".
    """
    result = await db.execute(
        select(Course).where(Course.user_id == user_id, Course.name == name)
    )
    existing = result.scalar_one_or_none()
    if existing:
        changed = False
        if description and existing.description != description:
            existing.description = description
            changed = True
        metadata = dict(existing.metadata_ or {})
        if metadata.get("source") != "canvas_scrape":
            metadata["source"] = "canvas_scrape"
            existing.metadata_ = metadata
            changed = True
        return "updated" if changed else "unchanged"

    course = Course(
        user_id=user_id,
        name=name,
        description=description,
        metadata_={"source": "canvas_scrape"},
    )
    db.add(course)
    await db.flush()
    logger.info("Created course from Canvas: %s", name)
    return "created"


async def _upsert_assignment(
    db: AsyncSession,
    course_id: uuid.UUID,
    title: str,
    due_date: datetime | None = None,
    assignment_type: str = "homework",
    metadata: dict | None = None,
) -> str:
    """Create/update assignment from Canvas scrape.

    Returns one of: "created", "updated", "unchanged".
    """
    result = await db.execute(
        select(Assignment).where(
            Assignment.course_id == course_id,
            Assignment.title == title,
        )
    )
    existing = result.scalar_one_or_none()
    merged_metadata = {"source": "canvas_scrape", **(metadata or {})}
    if existing:
        changed = False
        if due_date is not None and existing.due_date != due_date:
            existing.due_date = due_date
            changed = True
        if assignment_type and existing.assignment_type != assignment_type:
            existing.assignment_type = assignment_type
            changed = True
        if (existing.metadata_json or {}) != merged_metadata:
            existing.metadata_json = merged_metadata
            changed = True
        return "updated" if changed else "unchanged"

    assignment = Assignment(
        course_id=course_id,
        title=title,
        due_date=due_date,
        assignment_type=assignment_type,
        metadata_json=merged_metadata,
    )
    db.add(assignment)
    logger.info("Created assignment from Canvas: %s", title)
    return "created"


def _parse_date_text(text: str) -> datetime | None:
    """Best-effort parse of date strings from Canvas HTML."""
    if not text:
        return None

    # Try ISO format first (from datetime attributes)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        pass

    # Common Canvas formats: "Jan 15, 2025 at 11:59pm", "2025-01-15T23:59:00Z"
    formats = [
        "%b %d, %Y at %I:%M%p",
        "%b %d, %Y",
        "%B %d, %Y at %I:%M%p",
        "%B %d, %Y",
        "%m/%d/%Y",
    ]
    text_clean = text.strip().replace("\n", " ").replace("  ", " ")
    for fmt in formats:
        try:
            dt = datetime.strptime(text_clean, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None
