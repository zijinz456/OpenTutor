"""Automatic deadline extraction from educational documents.

Three-tier extraction strategy:
- Tier A (Regex): Zero-cost pattern matching for common date formats
- Tier B (LLM): Structured extraction for ambiguous/relative dates
- Tier C (Canvas API): Direct parsing of Canvas assignment due_at fields

Extracted deadlines are persisted as Assignment records with extraction metadata.
"""

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ingestion import Assignment

logger = logging.getLogger(__name__)

# ── Date parsing ──

# Month names for regex
_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

# Assignment type inference from surrounding context
_TYPE_KEYWORDS = {
    "exam": re.compile(r"(?i)\b(exam|midterm|final\s+exam|test)\b"),
    "quiz": re.compile(r"(?i)\b(quiz|assessment|evaluation)\b"),
    "homework": re.compile(r"(?i)\b(homework|hw|problem\s+set|ps\d)\b"),
    "project": re.compile(r"(?i)\b(project|report|presentation|essay|paper)\b"),
    "reading": re.compile(r"(?i)\b(reading|chapter|read\s+by)\b"),
}

# ── Date extraction patterns (priority-ordered) ──

# ISO 8601 / Canvas API format
_ISO_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)Z?"
)

# "Due: March 15, 2026" or "Deadline: March 15 2026"
_DUE_PHRASE_LONG_RE = re.compile(
    r"(?:due|deadline|submit|submission|turn\s+in)\s*(?:date|by)?\s*[:\-–—]?\s*"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s*\d{4})",
    re.IGNORECASE,
)

# "Due: 15/03/2026" or "Submit by 03-15-2026"
_DUE_PHRASE_NUMERIC_RE = re.compile(
    r"(?:due|deadline|submit|submission|turn\s+in)\s*(?:date|by)?\s*[:\-–—]?\s*"
    r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
    re.IGNORECASE,
)

# Standalone long-form dates: "March 15, 2026"
_STANDALONE_LONG_RE = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s*\d{4})",
    re.IGNORECASE,
)

# Relative academic dates (need LLM resolution)
_RELATIVE_WEEK_RE = re.compile(
    r"(?:Week|Wk)\s*(\d{1,2})\s*"
    r"(?:,?\s*(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun))?",
    re.IGNORECASE,
)


@dataclass
class ExtractedDeadline:
    """A deadline extracted from document text."""
    title: str
    due_date: datetime | None
    raw_date_text: str
    assignment_type: str  # exam, quiz, homework, project, reading
    confidence: float  # 0.0-1.0
    source_context: str  # surrounding text snippet
    needs_llm_resolution: bool = False


def _parse_date_flexible(text: str, prefer_day_first: bool = True) -> datetime | None:
    """Parse a date string in multiple formats. Returns UTC datetime or None."""
    text = text.strip().rstrip(".")

    # ISO 8601
    m = _ISO_DATE_RE.match(text)
    if m:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.fromisoformat(m.group(1) + "T" + m.group(2)).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

    # Long-form: "March 15, 2026" or "Mar 15 2026"
    long_match = re.match(
        r"((?:January|February|March|April|May|June|July|August|September|October|November|December"
        r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?)\s+(\d{1,2}),?\s*(\d{4})",
        text, re.IGNORECASE,
    )
    if long_match:
        month_str = long_match.group(1).rstrip(".").lower()
        month = _MONTH_NAMES.get(month_str)
        if month:
            try:
                return datetime(int(long_match.group(3)), month, int(long_match.group(2)),
                                23, 59, 0, tzinfo=timezone.utc)
            except ValueError:
                pass

    # Numeric: DD/MM/YYYY or MM/DD/YYYY
    num_match = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", text)
    if num_match:
        a, b, year_str = int(num_match.group(1)), int(num_match.group(2)), num_match.group(3)
        year = int(year_str)
        if year < 100:
            year += 2000
        try:
            if prefer_day_first:
                return datetime(year, b, a, 23, 59, 0, tzinfo=timezone.utc)
            else:
                return datetime(year, a, b, 23, 59, 0, tzinfo=timezone.utc)
        except ValueError:
            # Try the other interpretation
            try:
                if prefer_day_first:
                    return datetime(year, a, b, 23, 59, 0, tzinfo=timezone.utc)
                else:
                    return datetime(year, b, a, 23, 59, 0, tzinfo=timezone.utc)
            except ValueError:
                pass

    return None


def _infer_event_type(context: str) -> str:
    """Infer assignment type from surrounding text context."""
    for atype, pattern in _TYPE_KEYWORDS.items():
        if pattern.search(context):
            return atype
    return "homework"  # default


def _extract_event_title(context: str, assignment_type: str) -> str:
    """Extract a meaningful event title from surrounding context."""
    # Try to find named assignment/event lines (closest to the date)
    title_patterns = [
        # "### Assignment 1: Introduction to Accounting" or "**Quiz 2: Balance Sheet**"
        re.compile(r"((?:Assignment|Homework|Quiz|Exam|Test|Project|Lab|Essay|Midterm|Final)\s*\d*[:\s].{3,60})", re.IGNORECASE),
        # "Assignment 1" or "Quiz 2"
        re.compile(r"((?:Assignment|Homework|Quiz|Exam|Test|Project|Lab|Essay|Midterm|Final)\s*\d+)", re.IGNORECASE),
        # Markdown headers closest to the match (### Title)
        re.compile(r"(?:^|\n)\s*#{2,4}\s+(.{5,80})", re.MULTILINE),
        # Bold text (**Title**)
        re.compile(r"\*\*(.{5,80})\*\*"),
    ]
    for pat in title_patterns:
        m = pat.search(context)
        if m:
            title = m.group(1).strip().rstrip(":")
            if len(title) > 3:
                return title[:100]

    # Fallback: capitalize type
    return assignment_type.replace("_", " ").title()


def extract_deadlines_regex(content: str) -> list[ExtractedDeadline]:
    """Tier A: Zero-cost regex extraction of deadlines from document text.

    Scans full content for date patterns with surrounding context.
    Returns extracted deadlines sorted by date.
    """
    if not content or len(content) < 50:
        return []

    deadlines: list[ExtractedDeadline] = []
    seen_dates: set[str] = set()  # dedup by raw_date_text

    def _add_deadline(
        raw_date: str,
        match_start: int,
        confidence: float,
        needs_llm: bool = False,
    ) -> None:
        if raw_date in seen_dates:
            return
        seen_dates.add(raw_date)

        # Get surrounding context (200 chars before, 100 after)
        ctx_start = max(0, match_start - 200)
        ctx_end = min(len(content), match_start + len(raw_date) + 100)
        context = content[ctx_start:ctx_end]

        parsed_date = _parse_date_flexible(raw_date) if not needs_llm else None
        if parsed_date is None and not needs_llm:
            return  # unparseable, skip

        atype = _infer_event_type(context)
        title = _extract_event_title(context, atype)

        deadlines.append(ExtractedDeadline(
            title=title,
            due_date=parsed_date,
            raw_date_text=raw_date,
            assignment_type=atype,
            confidence=confidence,
            source_context=context[:300],
            needs_llm_resolution=needs_llm,
        ))

    # Pattern 1: ISO dates (highest confidence)
    for m in _ISO_DATE_RE.finditer(content):
        _add_deadline(m.group(0), m.start(), confidence=0.95)

    # Pattern 2: Due/deadline phrases with long-form dates
    for m in _DUE_PHRASE_LONG_RE.finditer(content):
        _add_deadline(m.group(1), m.start(), confidence=0.9)

    # Pattern 3: Due/deadline phrases with numeric dates
    for m in _DUE_PHRASE_NUMERIC_RE.finditer(content):
        _add_deadline(m.group(1), m.start(), confidence=0.75)

    # Pattern 4: Standalone long-form dates (lower confidence — might not be deadlines)
    # Only extract if near deadline-related keywords
    for m in _STANDALONE_LONG_RE.finditer(content):
        ctx_start = max(0, m.start() - 150)
        nearby = content[ctx_start:m.end() + 50].lower()
        deadline_keywords = ("due", "deadline", "submit", "exam", "quiz", "test", "assignment", "homework")
        if any(kw in nearby for kw in deadline_keywords):
            _add_deadline(m.group(1), m.start(), confidence=0.7)

    # Pattern 5: Relative week dates (need LLM resolution)
    for m in _RELATIVE_WEEK_RE.finditer(content):
        ctx_start = max(0, m.start() - 150)
        nearby = content[ctx_start:m.end() + 50].lower()
        deadline_keywords = ("due", "deadline", "submit", "assignment", "homework", "quiz")
        if any(kw in nearby for kw in deadline_keywords):
            _add_deadline(m.group(0), m.start(), confidence=0.3, needs_llm=True)

    # Sort by date (None dates at the end)
    deadlines.sort(key=lambda d: d.due_date or datetime.max.replace(tzinfo=timezone.utc))

    # Cap at 50 per document
    return deadlines[:50]


def extract_canvas_deadlines(assignments_data: list[dict]) -> list[ExtractedDeadline]:
    """Tier C: Parse Canvas API assignment objects directly.

    Canvas API returns structured assignment data with due_at fields.
    No regex or LLM needed — highest confidence extraction.
    """
    deadlines: list[ExtractedDeadline] = []
    for a in assignments_data:
        due_at = a.get("due_at")
        if not due_at:
            continue

        parsed = _parse_date_flexible(due_at)
        if not parsed:
            continue

        name = a.get("name") or a.get("title") or "Canvas Assignment"
        # Infer type from name
        atype = _infer_event_type(name)

        deadlines.append(ExtractedDeadline(
            title=name,
            due_date=parsed,
            raw_date_text=due_at,
            assignment_type=atype,
            confidence=0.99,
            source_context=f"Canvas API: {name}",
            needs_llm_resolution=False,
        ))

    return deadlines


# ── LLM extraction (Tier B) ──

_DEADLINE_EXTRACTION_PROMPT = """\
Extract all deadlines, due dates, and important dates from this educational document.

For each deadline found, return a JSON array with objects containing:
- "title": The name of the assignment, exam, quiz, or event
- "due_date": The date in ISO 8601 format (YYYY-MM-DDTHH:MM:SS)
- "type": One of: exam, quiz, homework, project, reading
- "confidence": 0.0-1.0 how confident you are about the date

{context_hint}

Document text:
{content}

Return ONLY a valid JSON array. If no deadlines found, return [].
"""


async def extract_deadlines_llm(
    content: str,
    course_name: str | None = None,
    semester_start: str | None = None,
) -> list[ExtractedDeadline]:
    """Tier B: LLM-enhanced extraction for ambiguous dates.

    Used for relative dates like "Week 5 Friday" and complex formatting.
    Best-effort — failures return empty list without blocking the pipeline.
    """
    from services.llm.router import get_llm_client
    from services.ingestion.content_trimmer import trim_for_llm

    try:
        client = get_llm_client("fast")
    except Exception:
        return []

    context_hint = ""
    if semester_start:
        context_hint += f"Semester starts on: {semester_start}\n"
    if course_name:
        context_hint += f"Course: {course_name}\n"

    trimmed = trim_for_llm(content, max_tokens=3000)
    prompt = _DEADLINE_EXTRACTION_PROMPT.format(
        content=trimmed,
        context_hint=context_hint,
    )

    try:
        response, _ = await client.extract(
            "You are a deadline extraction assistant. Output only valid JSON.",
            prompt,
        )

        # Parse JSON (handle markdown code fences)
        from libs.text_utils import strip_code_fences
        text = strip_code_fences(response)

        import json
        items = json.loads(text)
        if not isinstance(items, list):
            return []

        deadlines: list[ExtractedDeadline] = []
        for item in items[:50]:
            if not isinstance(item, dict):
                continue
            due_str = item.get("due_date", "")
            parsed = _parse_date_flexible(due_str) if due_str else None
            deadlines.append(ExtractedDeadline(
                title=item.get("title", "Unknown"),
                due_date=parsed,
                raw_date_text=due_str,
                assignment_type=item.get("type", "homework"),
                confidence=min(float(item.get("confidence", 0.6)), 1.0),
                source_context="LLM extraction",
                needs_llm_resolution=False,
            ))
        return deadlines

    except Exception as e:
        logger.debug("LLM deadline extraction failed: %s", e)
        return []


# ── Pipeline integration ──

async def extract_and_create_deadlines(
    db: AsyncSession,
    course_id: uuid.UUID,
    content: str,
    source_ingestion_id: uuid.UUID | None = None,
    canvas_assignments: list[dict] | None = None,
    course_name: str | None = None,
    semester_start: str | None = None,
) -> int:
    """Extract deadlines from content and create Assignment records.

    Orchestrates Tier A (regex) and Tier C (Canvas API) synchronously.
    Tier B (LLM) is called only for items with needs_llm_resolution=True.

    Returns number of assignments created/updated.
    """
    all_deadlines: list[ExtractedDeadline] = []

    # Tier A: Regex extraction
    all_deadlines.extend(extract_deadlines_regex(content))

    # Tier C: Canvas API
    if canvas_assignments:
        all_deadlines.extend(extract_canvas_deadlines(canvas_assignments))

    if not all_deadlines:
        return 0

    # Check for items needing LLM resolution
    needs_llm = [d for d in all_deadlines if d.needs_llm_resolution]
    resolved = [d for d in all_deadlines if not d.needs_llm_resolution and d.due_date]

    # Tier B: LLM for ambiguous dates (best-effort)
    if needs_llm and (semester_start or course_name):
        llm_results = await extract_deadlines_llm(content, course_name, semester_start)
        resolved.extend([d for d in llm_results if d.due_date])

    if not resolved:
        return 0

    # Dedup against existing assignments
    existing = await db.execute(
        select(Assignment).where(Assignment.course_id == course_id)
    )
    existing_assignments = existing.scalars().all()
    existing_titles = {a.title.lower().strip() for a in existing_assignments}

    created = 0
    for deadline in resolved:
        title_key = deadline.title.lower().strip()

        # Skip if title already exists (fuzzy match for Canvas)
        if title_key in existing_titles:
            # Update due_date if it was previously None and we now have one
            for ea in existing_assignments:
                if ea.title.lower().strip() == title_key and ea.due_date is None and deadline.due_date:
                    ea.due_date = deadline.due_date
                    ea.metadata_json = ea.metadata_json or {}
                    ea.metadata_json["extraction_source"] = "auto_update"
                    ea.metadata_json["extraction_confidence"] = deadline.confidence
                    created += 1
                    break
            continue

        existing_titles.add(title_key)
        assignment = Assignment(
            course_id=course_id,
            title=deadline.title,
            due_date=deadline.due_date,
            assignment_type=deadline.assignment_type,
            source_ingestion_id=source_ingestion_id,
            metadata_json={
                "extraction_source": "regex" if deadline.confidence >= 0.7 else "llm",
                "extraction_confidence": deadline.confidence,
                "raw_date_text": deadline.raw_date_text,
            },
        )
        db.add(assignment)
        created += 1

    if created:
        await db.flush()
        logger.info(
            "Deadline extraction: %d assignments created/updated for course %s",
            created, course_id,
        )

    return created
