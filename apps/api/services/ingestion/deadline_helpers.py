"""Helper constants, patterns, and functions for deadline extraction.

Contains:
- Month name mappings and assignment type keyword patterns
- Compiled regex patterns for date extraction (ISO, long-form, numeric, relative)
- ExtractedDeadline dataclass
- Date parsing and event title/type inference utilities
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

# ── Date parsing ──

# Month names for regex
MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

# Assignment type inference from surrounding context
TYPE_KEYWORDS = {
    "exam": re.compile(r"(?i)\b(exam|midterm|final\s+exam|test)\b"),
    "quiz": re.compile(r"(?i)\b(quiz|assessment|evaluation)\b"),
    "homework": re.compile(r"(?i)\b(homework|hw|problem\s+set|ps\d)\b"),
    "project": re.compile(r"(?i)\b(project|report|presentation|essay|paper)\b"),
    "reading": re.compile(r"(?i)\b(reading|chapter|read\s+by)\b"),
}

# ── Date extraction patterns (priority-ordered) ──

# ISO 8601 / Canvas API format
ISO_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)Z?"
)

# "Due: March 15, 2026" or "Deadline: March 15 2026"
DUE_PHRASE_LONG_RE = re.compile(
    r"(?:due|deadline|submit|submission|turn\s+in)\s*(?:date|by)?\s*[:\-–—]?\s*"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s*\d{4})",
    re.IGNORECASE,
)

# "Due: 15/03/2026" or "Submit by 03-15-2026"
DUE_PHRASE_NUMERIC_RE = re.compile(
    r"(?:due|deadline|submit|submission|turn\s+in)\s*(?:date|by)?\s*[:\-–—]?\s*"
    r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
    re.IGNORECASE,
)

# Standalone long-form dates: "March 15, 2026"
STANDALONE_LONG_RE = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s*\d{4})",
    re.IGNORECASE,
)

# Relative academic dates (need LLM resolution)
RELATIVE_WEEK_RE = re.compile(
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


def parse_date_flexible(text: str, prefer_day_first: bool = True) -> datetime | None:
    """Parse a date string in multiple formats. Returns UTC datetime or None."""
    text = text.strip().rstrip(".")

    # ISO 8601
    m = ISO_DATE_RE.match(text)
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
        month = MONTH_NAMES.get(month_str)
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


def infer_event_type(context: str) -> str:
    """Infer assignment type from surrounding text context."""
    for atype, pattern in TYPE_KEYWORDS.items():
        if pattern.search(context):
            return atype
    return "homework"  # default


def extract_event_title(context: str, assignment_type: str) -> str:
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
