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
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.ingestion import IngestionJob, Assignment
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)

_PHASE_LABELS = {
    "uploaded": "Upload received",
    "extracting": "Extracting content",
    "classifying": "Classifying material",
    "dispatching": "Building workspace artifacts",
    "embedding": "Building semantic index",
    "completed": "Ready",
    "failed": "Failed",
}


def _set_job_phase(
    job: IngestionJob,
    *,
    status: str,
    progress_percent: int,
    phase_label: str | None = None,
    embedding_status: str | None = None,
    nodes_created: int | None = None,
    error_message: str | None = None,
) -> None:
    job.status = status
    job.progress_percent = max(0, min(progress_percent, 100))
    job.phase_label = phase_label or _PHASE_LABELS.get(status)
    if embedding_status is not None:
        job.embedding_status = embedding_status
    if nodes_created is not None:
        job.nodes_created = nodes_created
    job.error_message = error_message


def _count_created_nodes(dispatch_result: Mapping[str, object] | None) -> int:
    if not dispatch_result:
        return 0
    total = 0
    for value in dispatch_result.values():
        if isinstance(value, int):
            total += value
    return total

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
    session_name: str | None = None,
) -> str:
    """Step 2: Extract text content via unified document_loader.

    Routes through Crawl4AI (web/PDF/HTML) + loader_dict (Office formats).
    """
    from services.ingestion.document_loader import extract_content as unified_extract

    try:
        _title, content = await unified_extract(
            file_path=file_path, url=url, session_name=session_name,
        )
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
    except Exception as e:
        logger.warning(f"LLM classification failed: {e}")
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
    session_name: str | None = None,
) -> IngestionJob:
    """Run the full 7-step ingestion pipeline.

    Args:
        pre_fetched_html: When provided (e.g. from authenticated scraping),
            Step 2 uses this content directly instead of re-fetching the URL.
        session_name: Optional Playwright session name for authenticated
            Canvas API access during extraction.

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
        duplicate_filters = [
            IngestionJob.content_hash == content_hash,
            IngestionJob.user_id == user_id,
            IngestionJob.status == "completed",
        ]
        if course_id:
            duplicate_filters.append(IngestionJob.course_id == course_id)

        existing = await db.execute(select(IngestionJob).where(*duplicate_filters))
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
        file_path=file_path,
        content_hash=content_hash,
        course_id=course_id,
        course_preset=course_id is not None,
        status="uploaded",
        progress_percent=5,
        phase_label=_PHASE_LABELS["uploaded"],
        embedding_status="pending",
    )
    db.add(job)
    await db.flush()
    await db.commit()

    try:
        # Step 1: MIME detection
        if filename:
            job.mime_type = detect_mime_type(filename, file_bytes)

        # Step 2: Content extraction
        _set_job_phase(job, status="extracting", progress_percent=20)
        await db.commit()

        # For Canvas URLs with auth, prefer deep Canvas REST API extraction
        extracted = ""
        canvas_file_urls: list[dict] = []
        canvas_quiz_questions: list[dict] = []
        if url and session_name:
            from services.scraper.canvas_detector import detect_canvas_url as _detect
            _cinfo = _detect(url)
            if _cinfo.is_canvas:
                from services.ingestion.document_loader import _try_canvas_api_deep
                deep_result = await _try_canvas_api_deep(url, session_name=session_name)
                if deep_result:
                    extracted = deep_result.content
                    canvas_file_urls = deep_result.file_urls
                    canvas_quiz_questions = deep_result.quiz_questions
                    logger.info(
                        "Canvas deep extraction: %d chars, %d pages, %d modules, %d files, %d quiz questions",
                        len(extracted), deep_result.pages_fetched,
                        deep_result.modules_found, len(canvas_file_urls),
                        len(canvas_quiz_questions),
                    )

        if not extracted and pre_fetched_html:
            # Authenticated scraping: content already fetched, parse HTML to text
            # Use Canvas-aware cleaning that preserves content containers
            from services.ingestion.document_loader import clean_soup_canvas_aware, get_text_from_soup
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(pre_fetched_html, "lxml")
            soup = clean_soup_canvas_aware(soup)
            extracted = get_text_from_soup(soup)

        if not extracted:
            extracted = await extract_content(
                file_path, url, job.mime_type or "", session_name=session_name,
            )
        job.extracted_markdown = extracted

        if not extracted:
            _set_job_phase(
                job,
                status="failed",
                progress_percent=20,
                embedding_status="failed",
                error_message="No content could be extracted",
            )
            await db.commit()
            return job

        # Step 3: 3-tier classification
        _set_job_phase(job, status="classifying", progress_percent=45)
        await db.commit()
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
        _set_job_phase(job, status="dispatching", progress_percent=70)
        await db.commit()

        # Step 6: Dispatch to business tables
        dispatch_result = await _dispatch_content(db, job)
        job.dispatched = True
        job.dispatched_to = dispatch_result
        nodes_created = _count_created_nodes(dispatch_result)
        needs_embedding = bool((dispatch_result or {}).get("content_tree"))
        if needs_embedding:
            _set_job_phase(
                job,
                status="embedding",
                progress_percent=90,
                embedding_status="pending",
                nodes_created=nodes_created,
            )
        else:
            _set_job_phase(
                job,
                status="completed",
                progress_percent=100,
                embedding_status="completed",
                nodes_created=nodes_created,
            )

    except Exception as e:
        _set_job_phase(
            job,
            status="failed",
            progress_percent=job.progress_percent or 0,
            embedding_status="failed",
            nodes_created=job.nodes_created,
            error_message=str(e),
        )
        logger.error(f"Ingestion pipeline failed: {e}")
        await db.commit()

    await db.flush()
    # Attach discovered Canvas file URLs and quiz questions for the caller to process
    job._canvas_file_urls = canvas_file_urls if canvas_file_urls else []
    job._canvas_quiz_questions = canvas_quiz_questions if canvas_quiz_questions else []
    return job


async def ingest_canvas_files(
    db_factory,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    file_urls: list[dict],
    session_name: str,
    canvas_domain: str,
) -> int:
    """Download and ingest Canvas files (PDFs, docs) discovered during deep extraction.

    Runs as a background task after the main course scrape completes.
    Each file is downloaded, then run through the ingestion pipeline.

    Returns number of files successfully ingested.
    """
    from services.ingestion.document_loader import download_canvas_file
    from config import settings

    ingested = 0
    save_dir = getattr(settings, "upload_dir", "uploads")

    for file_info in file_urls:
        try:
            # Download the file
            saved_path = await download_canvas_file(
                file_info,
                session_name=session_name,
                target_domain=canvas_domain,
                save_dir=save_dir,
            )
            if not saved_path:
                logger.debug("Skipped Canvas file (download failed): %s", file_info.get("filename"))
                continue

            # Read file bytes for dedup
            from pathlib import Path as _Path
            file_bytes = _Path(saved_path).read_bytes()
            if len(file_bytes) < 100:
                logger.debug("Skipped Canvas file (too small): %s", file_info.get("filename"))
                continue

            filename = file_info.get("filename", "file.pdf")

            # Run through ingestion pipeline
            async with db_factory() as file_db:
                job = await run_ingestion_pipeline(
                    db=file_db,
                    user_id=user_id,
                    file_path=saved_path,
                    filename=filename,
                    course_id=course_id,
                    file_bytes=file_bytes,
                )
                await file_db.commit()

                if job.status != "failed" and (job.nodes_created or 0) > 0:
                    ingested += 1
                    logger.info("Ingested Canvas file: %s (%d nodes)", filename, job.nodes_created or 0)
                else:
                    logger.debug("Canvas file ingestion produced no nodes: %s", filename)

        except Exception as e:
            logger.debug("Failed to ingest Canvas file %s: %s", file_info.get("filename"), e)

    logger.info("Canvas file ingestion complete: %d/%d files ingested", ingested, len(file_urls))
    return ingested


async def link_pdfs_to_canvas_topics(
    db_factory,
    course_id: uuid.UUID,
    file_urls: list[dict],
) -> int:
    """Phase 2: Reparent PDF root nodes under their matching Canvas topic nodes.

    Each file_url dict carries module_name + item_title metadata from Canvas.
    We find the content tree root node whose source_file matches the filename,
    then find/create a topic parent node matching module_name, and reparent.
    """
    from models.content import CourseContentTree

    linked = 0
    async with db_factory() as db:
        # Get all root nodes (parent_id IS NULL) for this course
        result = await db.execute(
            select(CourseContentTree).where(
                CourseContentTree.course_id == course_id,
                CourseContentTree.parent_id.is_(None),
            )
        )
        root_nodes = result.scalars().all()
        if not root_nodes:
            return 0

        # Build lookup: source_file → root node
        root_by_source: dict[str, CourseContentTree] = {}
        for node in root_nodes:
            if node.source_file:
                root_by_source[node.source_file] = node

        # Cache for topic parent nodes (module_name → node)
        topic_cache: dict[str, CourseContentTree] = {}

        # Get existing topic nodes — search all url/canvas_module nodes in tree
        # (they may be nested under a "Modules" parent from HTML scraping)
        existing_topics = await db.execute(
            select(CourseContentTree).where(
                CourseContentTree.course_id == course_id,
                CourseContentTree.source_type.in_(["url", "canvas_module"]),
            )
        )
        for topic_node in existing_topics.scalars().all():
            topic_cache[topic_node.title] = topic_node

        # Get max order_index for new topic nodes
        from sqlalchemy import func
        max_order = await db.execute(
            select(func.max(CourseContentTree.order_index)).where(
                CourseContentTree.course_id == course_id,
                CourseContentTree.parent_id.is_(None),
            )
        )
        next_order = (max_order.scalar() or 0) + 1

        already_linked: set[uuid.UUID] = set()

        for file_info in file_urls:
            module_name = file_info.get("module_name")
            filename = file_info.get("filename", "")
            if not module_name:
                continue

            # Try multiple matching strategies
            matched_root = None

            # Strategy 1: exact source_file match
            matched_root = root_by_source.get(filename)

            # Strategy 2: fuzzy match on filename stem
            if not matched_root:
                fn_stem = re.sub(r'\.pdf$', '', filename, flags=re.IGNORECASE).lower().strip()
                for source, node in root_by_source.items():
                    if node.id in already_linked:
                        continue
                    src_stem = re.sub(r'\.pdf$', '', source, flags=re.IGNORECASE).lower().strip()
                    if fn_stem and src_stem and (
                        fn_stem in src_stem
                        or src_stem in fn_stem
                        or (len(fn_stem) > 10 and fn_stem[:15] == src_stem[:15])
                    ):
                        matched_root = node
                        break

            if not matched_root or matched_root.parent_id is not None or matched_root.id in already_linked:
                continue
            already_linked.add(matched_root.id)

            # Find or create the topic parent node
            if module_name not in topic_cache:
                topic_node = CourseContentTree(
                    course_id=course_id,
                    title=module_name,
                    level=0,
                    order_index=next_order,
                    source_type="canvas_module",
                    source_file="canvas_structure",
                )
                db.add(topic_node)
                await db.flush()
                topic_cache[module_name] = topic_node
                next_order += 1

            parent_node = topic_cache[module_name]
            matched_root.parent_id = parent_node.id
            matched_root.level = 1
            linked += 1
            logger.info("Linked PDF '%s' under topic '%s'", filename, module_name)

        await db.commit()

    logger.info("PDF-topic linking: %d/%d files linked", linked, len(file_urls))
    return linked


async def auto_summarize_titles(
    db_factory,
    course_id: uuid.UUID,
) -> int:
    """Phase 3: Use AI to generate clean titles for content nodes with meaningless filenames."""
    from models.content import CourseContentTree

    def _is_meaningless_title(title: str) -> bool:
        """Check if a title is meaningless and needs AI renaming."""
        t = title.strip()
        if not t:
            return True
        # Filename-like meaningless patterns
        if re.match(
            r'^(\d+\.pdf|here\.+pdf|download\.pdf|file\.pdf|document\.pdf|'
            r'[a-f0-9]{8,}\.pdf|unnamed\.pdf|untitled\.pdf)$',
            t, re.IGNORECASE,
        ):
            return True
        # Title is just a sentence fragment (starts with bullet, lowercase, or short number)
        if t.startswith(('•', '-', '–', '—')) and len(t) < 80:
            return True
        # Pure number titles
        if re.match(r'^\d+\s', t) and len(t) < 30:
            return True
        return False

    updated = 0
    async with db_factory() as db:
        # Get all root/level-0 nodes that might have bad titles
        result = await db.execute(
            select(CourseContentTree).where(
                CourseContentTree.course_id == course_id,
                CourseContentTree.level.in_([0, 1]),
            )
        )
        nodes = result.scalars().all()

        for node in nodes:
            title = node.title or ""
            if not _is_meaningless_title(title):
                continue

            # Get content preview: use node's own content or first child's content
            content_preview = (node.content or "")[:500]
            if not content_preview:
                # Try to get content from first child
                child_result = await db.execute(
                    select(CourseContentTree).where(
                        CourseContentTree.parent_id == node.id,
                        CourseContentTree.content.isnot(None),
                    ).limit(1)
                )
                child = child_result.scalar_one_or_none()
                if child:
                    content_preview = (child.content or "")[:500]

            if not content_preview or len(content_preview) < 30:
                continue

            try:
                client = get_llm_client("fast")
                prompt = (
                    f"Based on this document content, generate a short descriptive title "
                    f"(max 60 chars). Just output the title, nothing else.\n\n"
                    f"Original filename: {title}\n"
                    f"Content preview:\n{content_preview}"
                )
                new_title, _ = await client.extract(
                    "You are a document title generator. Output only the title.",
                    prompt,
                )
                new_title = new_title.strip().strip('"\'')
                if new_title and 5 < len(new_title) < 100:
                    node.title = new_title
                    updated += 1
                    logger.info("Renamed '%s' → '%s'", title, new_title)
            except Exception as e:
                logger.debug("AI title generation failed for '%s': %s", title, e)

        await db.commit()

    logger.info("AI title summarization: %d nodes renamed", updated)
    return updated


async def auto_generate_notes(
    db_factory,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    """Phase 4: Auto-generate AI notes for content nodes after ingestion."""
    from models.content import CourseContentTree
    from services.parser.notes import restructure_notes
    from services.generated_assets import save_generated_asset

    generated = 0
    async with db_factory() as db:
        # Get content nodes with substantial content
        result = await db.execute(
            select(CourseContentTree).where(
                CourseContentTree.course_id == course_id,
                CourseContentTree.content.isnot(None),
            )
        )
        nodes = result.scalars().all()

        # Filter to nodes with meaningful content (>200 chars)
        eligible = [n for n in nodes if n.content and len(n.content) > 200]
        if not eligible:
            return 0

        # Process nodes — cap at 30 to avoid excessive API calls
        import asyncio as _asyncio
        for node in eligible[:30]:
            try:
                # Trim content to avoid very long API calls; add per-node timeout
                content_trimmed = node.content[:4000] if node.content else ""
                ai_content = await _asyncio.wait_for(
                    restructure_notes(
                        content_trimmed,
                        node.title,
                        note_format="bullet_point",
                    ),
                    timeout=60,
                )
                if ai_content and len(ai_content) > 50:
                    await save_generated_asset(
                        db,
                        user_id=user_id,
                        course_id=course_id,
                        asset_type="notes",
                        title=node.title,
                        content={"markdown": ai_content},
                        metadata={
                            "source_node_id": str(node.id),
                            "auto_generated": True,
                            "format": "bullet_point",
                        },
                    )
                    generated += 1
                    logger.info("Auto-generated notes for node '%s'", node.title)
            except Exception as e:
                logger.debug("Auto-generate notes failed for '%s': %s", node.title, e)

        await db.commit()

    logger.info("Auto-generated notes: %d/%d nodes processed", generated, len(eligible))
    return generated


async def _dispatch_content(db: AsyncSession, job: IngestionJob) -> dict:
    """Step 6: Dispatch extracted content to appropriate business tables."""
    result = {}

    if not job.course_id or not job.extracted_markdown:
        return result

    category = job.content_category or "other"
    source_name = (job.original_filename or "").lower()
    inferred_text_source = (
        source_name.endswith((".md", ".txt", ".rst", ".html", ".htm"))
        or (job.mime_type or "").startswith("text/")
        or job.source_type == "url"
    )

    if category in ("lecture_slides", "textbook", "notes", "syllabus") or (
        category == "other" and inferred_text_source
    ):
        # Build content tree using PageIndex pattern
        from services.parser.pdf import _markdown_to_tree
        from models.content import CourseContentTree
        source_label = job.original_filename or job.url or "Untitled"

        # Dedup: remove existing content tree nodes from the same source
        # before inserting new ones (prevents duplicates on re-ingestion)
        existing = await db.execute(
            select(CourseContentTree).where(
                CourseContentTree.course_id == job.course_id,
                CourseContentTree.source_file == source_label,
            )
        )
        old_nodes = existing.scalars().all()
        if old_nodes:
            old_ids = [n.id for n in old_nodes]
            # Nullify FK references from practice_problems before deleting
            from models.practice import PracticeProblem
            await db.execute(
                PracticeProblem.__table__.update()
                .where(PracticeProblem.content_node_id.in_(old_ids))
                .values(content_node_id=None)
            )
            for old_node in old_nodes:
                await db.delete(old_node)
            await db.flush()
            logger.info("Dedup: removed %d existing nodes for source %s", len(old_nodes), source_label)

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
