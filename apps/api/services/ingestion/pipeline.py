"""Unified classification pipeline — 7-step ingestion.

Step 0: Preprocessing (xxhash dedup, expanded filename regex, content heuristics)
Step 1: MIME detection (filetype → python-magic → extension)
Step 2: Content extraction (Crawl4AI → loader_dict → legacy fallbacks)
Step 3: 3-tier classification (filename regex → content heuristics → LLM)
Step 4: Course fuzzy matching (thefuzz)
Step 5: Store to ingestion_jobs table
Step 6: Dispatch to business tables (content_tree, assignments)

References:
- Crawl4AI: unified content extraction (web + PDF + HTML)
- GPT-Researcher: loader_dict for Office formats, clean_soup for HTML
- Deep-Research: token-aware content trimming (trimPrompt pattern)
- PageIndex: code-block-aware tree building, tree thinning
- Marker: filetype MIME detection pattern
- Crawl4AI: xxhash for fast content dedup
"""

import hashlib
import logging
import mimetypes
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.ingestion import IngestionJob, Assignment
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


# ── Step 1: MIME detection (3-tier: filetype → python-magic → extension) ──

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
        except Exception:
            pass

        # Tier 2: python-magic
        try:
            import magic

            return magic.from_buffer(content_bytes[:8192], mime=True)
        except ImportError:
            pass
        except Exception:
            pass

    # Tier 3: extension-based
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


# ── Step 2: Content extraction ──

async def extract_content(
    file_path: str | None,
    url: str | None,
    mime_type: str,
) -> str:
    """Step 2: Extract text content via unified document_loader.

    Routes through Crawl4AI (web/PDF/HTML) + loader_dict (Office formats).
    """
    from services.ingestion.document_loader import extract_content as unified_extract

    try:
        _title, content = await unified_extract(file_path=file_path, url=url)
        return content
    except Exception as e:
        logger.warning(f"Content extraction failed: {e}")
        return ""


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

        client = get_llm_client()
        trimmed = trim_for_llm(content, max_tokens=2000)
        prompt = CLASSIFICATION_PROMPT.format(content=trimmed)
        result = await client.extract(
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
    except Exception as e:
        logger.warning(f"LLM classification failed: {e}")
        return "other"


async def classify_document(content: str, filename: str) -> tuple[str, str]:
    """3-tier classification with explicit method reporting."""
    category = classify_by_filename(filename)
    if category:
        return category, "filename_regex"

    if not content or len(content) < 50:
        return "other", "llm_classification"

    category = classify_by_content_heuristics(content)
    if category:
        return category, "content_heuristics"

    return await classify_content(content), "llm_classification"


# ── Step 4: Course fuzzy matching ──

async def match_course(
    db: AsyncSession,
    filename: str,
    content: str,
    user_id: uuid.UUID,
) -> uuid.UUID | None:
    """Step 4: Match ingested content to an existing course.

    Uses thefuzz for fuzzy string matching against course names.
    Falls back to None if no confident match (user assigns manually).
    """
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


# ── Step 5 & 6: Full pipeline ──

async def run_ingestion_pipeline(
    db: AsyncSession,
    user_id: uuid.UUID,
    file_path: str | None = None,
    url: str | None = None,
    filename: str = "",
    course_id: uuid.UUID | None = None,
    file_bytes: bytes | None = None,
    pre_fetched_html: str | None = None,
) -> IngestionJob:
    """Run the full 7-step ingestion pipeline.

    Args:
        pre_fetched_html: When provided (e.g. from authenticated scraping),
            Step 2 uses this content directly instead of re-fetching the URL.

    Returns the IngestionJob with results.
    """
    # Step 0: Content hash dedup (xxhash ~10x faster than SHA-256, ported from Crawl4AI)
    content_hash = None
    if file_bytes:
        try:
            import xxhash

            content_hash = xxhash.xxh64(file_bytes).hexdigest()
        except ImportError:
            content_hash = hashlib.sha256(file_bytes).hexdigest()
        # Check for duplicates
        existing = await db.execute(
            select(IngestionJob).where(
                IngestionJob.content_hash == content_hash,
                IngestionJob.user_id == user_id,
                IngestionJob.status == "completed",
            )
        )
        dupe = existing.scalar_one_or_none()
        if dupe:
            logger.info(f"Duplicate detected: {filename} (hash: {content_hash[:12]})")
            return dupe

    # Create job
    job = IngestionJob(
        user_id=user_id,
        source_type="file" if file_path else "url",
        original_filename=filename,
        url=url,
        content_hash=content_hash,
        course_id=course_id,
        course_preset=course_id is not None,
        status="extracting",
    )
    db.add(job)
    await db.flush()

    try:
        # Step 1: MIME detection
        if filename:
            job.mime_type = detect_mime_type(filename, file_bytes)

        # Step 2: Content extraction
        job.status = "extracting"
        if pre_fetched_html:
            # Authenticated scraping: content already fetched, parse HTML to text
            from services.ingestion.document_loader import clean_soup, get_text_from_soup
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(pre_fetched_html, "lxml")
            soup = clean_soup(soup)
            extracted = get_text_from_soup(soup)
        else:
            extracted = await extract_content(file_path, url, job.mime_type or "")
        job.extracted_markdown = extracted

        if not extracted:
            job.status = "failed"
            job.error_message = "No content could be extracted"
            return job

        # Step 3: 3-tier classification
        job.status = "classifying"
        job.content_category, job.classification_method = await classify_document(
            extracted,
            filename,
        )

        # Step 4: Course matching (if not preset)
        if not course_id:
            matched_id = await match_course(db, filename, extracted, user_id)
            if matched_id:
                job.course_id = matched_id

        # Step 5: Status update
        job.status = "dispatching"

        # Step 6: Dispatch to business tables
        dispatch_result = await _dispatch_content(db, job)
        job.dispatched = True
        job.dispatched_to = dispatch_result
        job.status = "completed"

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        logger.error(f"Ingestion pipeline failed: {e}")

    await db.flush()
    return job


async def _dispatch_content(db: AsyncSession, job: IngestionJob) -> dict:
    """Step 6: Dispatch extracted content to appropriate business tables."""
    result = {}

    if not job.course_id or not job.extracted_markdown:
        return result

    category = job.content_category or "other"

    if category in ("lecture_slides", "textbook", "notes", "syllabus"):
        # Build content tree using PageIndex pattern
        from services.parser.pdf import _markdown_to_tree
        source_label = job.original_filename or job.url or "Untitled"
        nodes = _markdown_to_tree(
            markdown=job.extracted_markdown,
            course_id=job.course_id,
            source_file=source_label,
        )
        for node in nodes:
            # Normalize source metadata to the ingestion source (file/url).
            node.source_type = job.source_type
            node.source_file = source_label
            db.add(node)
        await db.flush()  # Assign IDs before indexing

        # Build full-text search vectors for BM25
        node_ids = [str(node.id) for node in nodes]
        from services.search.indexer import index_content_nodes
        await index_content_nodes(db, node_ids)

        result["content_tree"] = len(nodes)

    elif category == "assignment":
        # Extract assignment info
        from services.ingestion.content_trimmer import trim_for_llm

        assignment = Assignment(
            course_id=job.course_id,
            title=job.original_filename or "Assignment",
            description=trim_for_llm(job.extracted_markdown, max_tokens=2000) if job.extracted_markdown else None,
            assignment_type="homework",
            source_ingestion_id=job.id,
        )
        db.add(assignment)
        result["assignments"] = 1

    elif category == "exam_schedule":
        from services.ingestion.content_trimmer import trim_for_llm

        assignment = Assignment(
            course_id=job.course_id,
            title=job.original_filename or "Exam",
            description=trim_for_llm(job.extracted_markdown, max_tokens=2000) if job.extracted_markdown else None,
            assignment_type="exam",
            source_ingestion_id=job.id,
        )
        db.add(assignment)
        result["assignments"] = 1

    return result
