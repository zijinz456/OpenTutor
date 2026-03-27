"""Classification and MIME detection utilities for the ingestion pipeline.

Step 0: Filename regex patterns + content heuristics (zero LLM cost)
Step 1: MIME detection (filetype -> python-magic -> extension)
Step 3: LLM classification fallback
"""

import logging
import mimetypes
import re

from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)

# ── Step 0: Filename regex patterns (expanded) ──

FILENAME_PATTERNS = {
    r"(?i)lecture|slides|ppt|lec\d|class.?note|presentation": "lecture_slides",
    r"(?i)chapter|textbook|reading|book|reference|manual|guide": "textbook",
    r"(?i)hw|homework|assignment|problem.?set|ps\d|worksheet|exercise|lab\b|project\b": "assignment",
    r"(?i)exam|midterm|final|test|quiz|assessment": "exam_schedule",
    r"(?i)syllabus|schedule|outline|grading|course.?info|catalog": "syllabus",
    r"(?i)notes?|summary|review|cheat.?sheet|study.?guide|recap": "notes",
}

# Content heuristics — patterns matched against extracted text (zero LLM cost)
CONTENT_HEURISTICS = [
    (r"(?i)(due\s+date|submit\s+by|deadline|turn\s+in|submission)", "assignment"),
    (r"(?i)(grading\s+policy|office\s+hours|prerequisites|course\s+description|learning\s+objectives)", "syllabus"),
    (r"(?i)(slide\s+\d+|next\s+slide|previous\s+slide)", "lecture_slides"),
    (r"(?i)(exam\s+\d|midterm\s+exam|final\s+exam|quiz\s+\d).*\d{1,2}[/\-]\d{1,2}", "exam_schedule"),
    (r"(?i)(chapter\s+\d+|section\s+\d+\.\d+|theorem\s+\d+|definition\s+\d+)", "textbook"),
]


def classify_by_filename(filename: str) -> str | None:
    """Step 0: Try to classify by filename regex (zero LLM cost)."""
    for pattern, category in FILENAME_PATTERNS.items():
        if re.search(pattern, filename):
            return category
    return None


def classify_by_content_heuristics(content: str) -> str | None:
    """Step 0.5: Try to classify by content patterns (zero LLM cost).

    Scans the first 3000 characters for telltale phrases.
    """
    sample = content[:3000]
    scores: dict[str, int] = {}

    for pattern, category in CONTENT_HEURISTICS:
        matches = re.findall(pattern, sample)
        if matches:
            scores[category] = scores.get(category, 0) + len(matches)

    if scores:
        # Return category with highest match count
        return max(scores, key=scores.get)
    return None


# ── Step 1: MIME detection (3-tier: filetype -> python-magic -> extension) ──

def detect_mime_type(filename: str, content_bytes: bytes | None = None) -> str:
    """Step 1: Detect MIME type with 3-tier fallback.

    Tier 1: filetype (pure Python magic-number detection, ported from Marker registry.py)
    Tier 2: python-magic (libmagic binding)
    Tier 3: Extension-based (mimetypes stdlib)
    """
    if content_bytes:
        # Tier 1: filetype library (fast, pure Python)
        try:
            import filetype

            kind = filetype.guess(content_bytes[:8192])
            if kind:
                return kind.mime
        except ImportError:
            pass
        except (ValueError, OSError, RuntimeError) as e:
            logger.debug("filetype MIME detection failed: %s", e)

        # Tier 2: python-magic
        try:
            import magic

            return magic.from_buffer(content_bytes[:8192], mime=True)
        except ImportError:
            pass
        except (ValueError, OSError, RuntimeError) as e:
            logger.debug("python-magic MIME detection failed: %s", e)

    # Tier 3: extension-based
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


# ── Step 2: Content extraction ──

async def extract_content_with_title(
    file_path: str | None,
    url: str | None,
    mime_type: str,
    session_name: str | None = None,
) -> tuple[str, str]:
    """Step 2: Extract title + text content via unified document_loader."""
    from services.ingestion.document_loader import extract_content as unified_extract

    try:
        return await unified_extract(
            file_path=file_path, url=url, session_name=session_name,
        )
    except (IOError, OSError) as e:
        logger.warning("Content extraction I/O error: %s", e)
        return "", ""
    except (ValueError, RuntimeError) as e:
        logger.exception("Content extraction failed unexpectedly")
        return "", ""


async def extract_content(
    file_path: str | None,
    url: str | None,
    mime_type: str,
    session_name: str | None = None,
) -> str:
    """Step 2: Extract text content via unified document_loader.

    Routes through Crawl4AI (web/PDF/HTML) + loader_dict (Office formats).
    """
    _title, content = await extract_content_with_title(
        file_path=file_path,
        url=url,
        mime_type=mime_type,
        session_name=session_name,
    )
    return content


# ── Step 3: LLM classification ──

CLASSIFICATION_PROMPT = """Classify this educational document into ONE of these categories:

Categories:
- lecture_slides: Lecture slides, presentations, class notes from professor
- textbook: Textbook chapters, readings, reference material
- assignment: Homework, problem sets, coding assignments
- exam_schedule: Exams, quizzes, midterms, finals, test dates
- syllabus: Course syllabus, schedule, grading policy
- notes: Student notes, study guides, review sheets
- other: Anything that doesn't fit above

Respond with ONLY the category name, nothing else.

Document (first 2000 chars):
{content}"""


async def classify_content(content: str) -> str:
    """LLM-only fallback classification for non-trivial content."""
    try:
        from services.ingestion.content_trimmer import trim_for_llm

        client = get_llm_client("fast")
        trimmed = trim_for_llm(content, max_tokens=2000)
        prompt = CLASSIFICATION_PROMPT.format(content=trimmed)
        result, _ = await client.extract(
            "You are a document classifier. Output only the category name.",
            prompt,
        )
        result = result.strip().lower()

        valid_categories = {
            "lecture_slides", "textbook", "assignment",
            "exam_schedule", "syllabus", "notes", "other",
        }
        if result in valid_categories:
            return result
        # Fuzzy match
        for cat in valid_categories:
            if cat in result:
                return cat
        return "other"
    except (ConnectionError, TimeoutError) as e:
        logger.warning("LLM classification network error: %s", e)
        return "other"
    except (ValueError, RuntimeError) as e:
        logger.exception("LLM classification failed")
        return "other"


async def classify_document(content: str, filename: str) -> tuple[str, str]:
    """3-tier classification with explicit method reporting."""
    category = classify_by_filename(filename)
    if category:
        return category, "filename_regex"

    normalized_name = (filename or "").lower()
    if normalized_name.endswith((".md", ".txt", ".rst", ".html", ".htm")):
        return "notes", "text_fallback"

    if not content or len(content) < 50:
        return "other", "llm_classification"

    category = classify_by_content_heuristics(content)
    if category:
        return category, "content_heuristics"

    return await classify_content(content), "llm_classification"


# ── Step 4: Course fuzzy matching ──

async def match_course(
    db,  # AsyncSession
    filename: str,
    content: str,
    user_id,
) -> "uuid.UUID | None":
    """Step 4: Match ingested content to an existing course.

    Uses thefuzz for fuzzy string matching against course names.
    Falls back to None if no confident match (user assigns manually).
    """
    import uuid

    from sqlalchemy import select

    from models.course import Course

    result = await db.execute(select(Course).where(Course.user_id == user_id))
    courses = result.scalars().all()

    if not courses:
        return None

    if len(courses) == 1:
        return courses[0].id

    # Try fuzzy matching
    try:
        from thefuzz import fuzz
    except ImportError:
        # Fallback: simple substring matching
        filename_lower = filename.lower()
        for course in courses:
            if course.name.lower() in filename_lower:
                return course.id
        return None

    best_score = 0
    best_match = None
    search_text = f"{filename} {content[:200]}".lower()

    for course in courses:
        score = fuzz.partial_ratio(course.name.lower(), search_text)
        if score > best_score:
            best_score = score
            best_match = course

    # Only match if confidence is high enough
    if best_score >= 70 and best_match:
        return best_match.id

    return None
