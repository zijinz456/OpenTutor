"""Unified content extraction — Crawl4AI as primary engine + GPT-Researcher loader_dict for Office formats.

Architecture:
- Crawl4AI: web pages (HTTP/HTTPS), PDF (URL + local via file://), local HTML
- loader_dict: DOCX, PPTX, XLSX, CSV, TXT, MD (Office/text formats Crawl4AI doesn't support)
- Fallback layers: httpx + clean_soup, trafilatura, Playwright cascade

Features:
- BM25 content filtering for focused extraction from noisy web pages
- Batch URL crawling via arun_many() for bulk ingestion
- Media/links metadata extraction and storage

References:
- Crawl4AI: AsyncWebCrawler, NaivePDFProcessorStrategy (processors/pdf/processor.py)
- Crawl4AI: BM25ContentFilter (content_filter_strategy.py L381-530)
- GPT-Researcher: DocumentLoader loader_dict (document/document.py L66-78)
- GPT-Researcher: clean_soup(), get_text_from_soup() (scraper/utils.py L94-132)
"""

import logging
import re
import asyncio
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Office formats handled by loader_dict (GPT-Researcher pattern)
OFFICE_EXTENSIONS = {"doc", "docx", "pptx", "csv", "xls", "xlsx"}

# Text formats read directly
TEXT_EXTENSIONS = {"txt", "md", "rst"}
_marker_models: dict | None = None


@dataclass
class ExtractionResult:
    """Rich extraction result with metadata from Crawl4AI."""

    title: str = ""
    content: str = ""
    images: list[dict] = field(default_factory=list)    # [{url, score, alt, ...}]
    links_internal: list[dict] = field(default_factory=list)
    links_external: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)         # OG/Twitter/standard meta tags


async def extract_content(
    file_path: str | None = None,
    url: str | None = None,
    query: str | None = None,
    session_name: str | None = None,
) -> tuple[str, str]:
    """Unified content extraction entry point.

    Returns (title, markdown_content).
    Routes to the appropriate extractor based on input type and format.

    Args:
        query: Optional search query for BM25 content filtering (Crawl4AI).
               When provided, noisy web pages are filtered to keep only
               query-relevant sections.
        session_name: Optional Playwright session name for authenticated Canvas API access.
    """
    if url:
        return await _extract_from_url(url, query=query, session_name=session_name)

    if not file_path:
        return "", ""

    ext = Path(file_path).suffix.lstrip(".").lower()

    # PDF and HTML → Crawl4AI via file:// protocol
    if ext == "pdf":
        return await _extract_local_with_crawl4ai(file_path)
    if ext in ("html", "htm"):
        return await _extract_local_with_crawl4ai(file_path)

    # Office formats → GPT-Researcher loader_dict
    if ext in OFFICE_EXTENSIONS:
        return await asyncio.to_thread(_extract_with_loader_dict, file_path, ext)

    # Text formats → direct read
    if ext in TEXT_EXTENSIONS:
        return await asyncio.to_thread(_extract_plain_text, file_path)

    # Unknown → try text read
    return await asyncio.to_thread(_extract_plain_text, file_path)


def _build_crawl4ai_config(query: str | None = None):
    """Build Crawl4AI CrawlerRunConfig with optional BM25 filtering."""
    from crawl4ai import CrawlerRunConfig
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

    markdown_generator = DefaultMarkdownGenerator()
    if query:
        try:
            from crawl4ai.content_filter_strategy import BM25ContentFilter

            markdown_generator = DefaultMarkdownGenerator(
                content_filter=BM25ContentFilter(user_query=query, bm25_threshold=1.0)
            )
        except ImportError:
            pass
    return CrawlerRunConfig(
        excluded_tags=["nav", "footer", "sidebar"],
        word_count_threshold=100,
        markdown_generator=markdown_generator,
    )


async def extract_content_rich(
    url: str,
    query: str | None = None,
) -> ExtractionResult:
    """Rich URL extraction returning content with media, links, and metadata.

    Uses Crawl4AI with optional BM25 filtering. Falls back to basic extraction.
    """
    try:
        from crawl4ai import AsyncWebCrawler

        async with AsyncWebCrawler() as crawler:
            config = _build_crawl4ai_config(query)
            result = await crawler.arun(url=url, config=config)
            if result.success:
                return _crawl_result_to_extraction(result, url, query)
    except ImportError:
        logger.debug("crawl4ai not installed, falling back to basic extraction")
    except Exception as e:
        logger.debug(f"Crawl4AI rich extraction failed for {url}: {e}")

    # Fallback to basic extraction
    title, content = await _extract_from_url(url, query=query)
    return ExtractionResult(title=title, content=content)


async def extract_content_batch(
    urls: list[str],
    query: str | None = None,
) -> list[ExtractionResult]:
    """Batch URL extraction using Crawl4AI arun_many() for parallel crawling.

    Significantly faster than sequential extraction for multiple URLs.
    Falls back to sequential extraction if Crawl4AI is unavailable.
    """
    if not urls:
        return []

    try:
        from crawl4ai import AsyncWebCrawler

        config = _build_crawl4ai_config(query)

        async with AsyncWebCrawler() as crawler:
            results = await crawler.arun_many(urls=urls, config=config)
            extractions = []
            for result in results:
                if result.success:
                    extractions.append(
                        _crawl_result_to_extraction(result, result.url, query)
                    )
                else:
                    extractions.append(ExtractionResult(title=result.url))
            return extractions

    except ImportError:
        logger.debug("crawl4ai not installed, falling back to sequential extraction")
    except Exception as e:
        logger.debug(f"Crawl4AI batch extraction failed: {e}")

    # Fallback: sequential extraction
    results = []
    for url in urls:
        title, content = await _extract_from_url(url, query=query)
        results.append(ExtractionResult(title=title, content=content))
    return results


def _crawl_result_to_extraction(result, url: str, query: str | None = None) -> ExtractionResult:
    """Convert a Crawl4AI CrawlResult to ExtractionResult with media/links/metadata."""
    md = getattr(result, "markdown", None)
    if md is None:
        return ExtractionResult(title=url)

    # Content: prefer BM25-filtered when query was provided
    content = ""
    if query and hasattr(md, "fit_markdown") and md.fit_markdown:
        content = md.fit_markdown
    if not content:
        content = md.raw_markdown if hasattr(md, "raw_markdown") else str(md)

    # Title from metadata
    title = url
    if result.metadata and isinstance(result.metadata, dict):
        title = result.metadata.get("title", url) or url

    # Images — Crawl4AI provides scored image data
    images = []
    if hasattr(result, "media") and isinstance(result.media, dict):
        for img in result.media.get("images", []):
            images.append({
                "src": img.get("src", ""),
                "alt": img.get("alt", ""),
                "score": img.get("score", 0),
                "description": img.get("desc", ""),
            })

    # Links — internal and external
    links_internal = []
    links_external = []
    if hasattr(result, "links") and isinstance(result.links, dict):
        for link in result.links.get("internal", []):
            links_internal.append({
                "href": link.get("href", ""),
                "text": link.get("text", ""),
            })
        for link in result.links.get("external", []):
            links_external.append({
                "href": link.get("href", ""),
                "text": link.get("text", ""),
            })

    # Metadata
    metadata = {}
    if result.metadata and isinstance(result.metadata, dict):
        metadata = result.metadata

    return ExtractionResult(
        title=title,
        content=content,
        images=images,
        links_internal=links_internal,
        links_external=links_external,
        metadata=metadata,
    )


# ── Canvas API extraction (structured data via REST API) ──
# Borrowed from learning-agent-extension: use Canvas REST API (/api/v1/)
# to get structured data instead of scraping rendered HTML.


def _load_session_cookies(
    session_name: str | None,
    target_domain: str | None = None,
) -> dict[str, str]:
    """Load cookies from a saved Playwright session file for httpx use.

    Reads the storageState JSON and extracts cookies as a flat dict
    suitable for httpx.AsyncClient(cookies=...).

    Args:
        target_domain: If provided, only return cookies that match this domain
            (exact match or parent domain match). This is critical for Canvas
            where auth cookies (canvas_session, _csrf_token) live on the
            exact domain, not on analytics tracking domains.
    """
    if not session_name:
        return {}
    try:
        from services.browser.session_manager import SessionManager
        import json

        state_path = SessionManager.state_file(session_name)
        if not state_path.exists():
            return {}

        state = json.loads(state_path.read_text())
        cookies = {}
        for cookie in state.get("cookies", []):
            cookie_domain = cookie.get("domain", "").lstrip(".")
            name = cookie["name"]

            if target_domain:
                # Match exact domain or parent domain
                td = target_domain.lstrip(".")
                if cookie_domain == td or td.endswith("." + cookie_domain):
                    cookies[name] = cookie["value"]
            else:
                cookies[name] = cookie["value"]
        return cookies
    except Exception as e:
        logger.debug("Failed to load session cookies for %s: %s", session_name, e)
        return {}


@dataclass
class CanvasExtraction:
    """Result of deep Canvas API extraction."""
    title: str
    content: str
    file_urls: list[dict] = field(default_factory=list)
    """List of discovered file dicts: {"url": str, "filename": str, "content_type": str}"""
    pages_fetched: int = 0
    modules_found: int = 0
    quiz_questions: list[dict] = field(default_factory=list)
    """Parsed quiz questions with correct answers mapped from Canvas API weight field."""


def _parse_canvas_quiz_question(question: dict, quiz_title: str) -> dict | None:
    """Parse a Canvas API quiz question into a PracticeProblem-compatible dict.

    Canvas answer objects include a `weight` field (100 = correct, 0 = wrong).
    """
    from bs4 import BeautifulSoup

    q_text = question.get("question_text", "")
    if not q_text:
        return None
    soup = BeautifulSoup(q_text, "lxml")
    clean_text = soup.get_text(strip=True)
    if not clean_text:
        return None

    canvas_type = question.get("question_type", "")
    TYPE_MAP = {
        "multiple_choice_question": "mc",
        "true_false_question": "tf",
        "short_answer_question": "short_answer",
        "multiple_answers_question": "select_all",
        "fill_in_multiple_blanks_question": "fill_blank",
        "essay_question": "free_response",
        "matching_question": "matching",
    }
    question_type = TYPE_MAP.get(canvas_type, "mc")

    answers = question.get("answers", [])
    options = None
    correct_answer = None

    if question_type in ("mc", "tf", "select_all"):
        options = {}
        correct_keys = []
        for i, ans in enumerate(answers):
            key = chr(ord("A") + i) if i < 26 else str(i + 1)
            ans_text = ans.get("text", "") or ans.get("html", "")
            if ans_text:
                if not ans.get("text") and ans.get("html"):
                    s = BeautifulSoup(ans_text, "lxml")
                    ans_text = s.get_text(strip=True)
                options[key] = ans_text
                weight = ans.get("weight", 0)
                if weight and float(weight) > 0:
                    correct_keys.append(key)
        correct_answer = ",".join(correct_keys) if correct_keys else None
    elif question_type == "short_answer":
        for ans in answers:
            ans_text = ans.get("text", "")
            weight = ans.get("weight", 0)
            if ans_text and weight and float(weight) > 0:
                correct_answer = ans_text
                break

    return {
        "question_type": question_type,
        "question": clean_text,
        "options": options,
        "correct_answer": correct_answer,
        "explanation": None,
        "difficulty_layer": 2,
        "problem_metadata": {
            "core_concept": quiz_title,
            "bloom_level": "understand",
            "potential_traps": [],
            "layer_justification": "Imported from Canvas quiz",
            "skill_focus": "concept check",
            "source_section": quiz_title,
            "source_kind": "canvas_import",
        },
    }


def _extract_file_urls_from_html(
    html: str,
    base_url: str,
    module_name: str | None = None,
    item_title: str | None = None,
) -> list[dict]:
    """Extract PDF and document file URLs from Canvas page HTML body.

    Finds links to files hosted on Canvas (course files, module attachments)
    and returns them as structured dicts for downstream downloading.
    """
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin, urlparse

    soup = BeautifulSoup(html, "lxml")
    files: list[dict] = []
    seen_urls: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(base_url, href)

        # Skip already-seen URLs
        if full_url in seen_urls:
            continue

        # Match Canvas file URLs: /courses/{id}/files/{file_id}
        # or direct download links: /files/{file_id}/download
        is_canvas_file = bool(re.search(r"/files/\d+", href))
        # Match direct PDF/document links
        parsed = urlparse(full_url)
        ext = Path(parsed.path).suffix.lower()
        is_doc_link = ext in {".pdf", ".doc", ".docx", ".pptx", ".ppt", ".xlsx", ".xls"}

        if is_canvas_file or is_doc_link:
            seen_urls.add(full_url)
            link_text = a_tag.get_text(strip=True) or Path(parsed.path).stem
            # Normalize Canvas file URLs to download form
            download_url = full_url
            if is_canvas_file and "/download" not in full_url:
                # Strip query params like ?wrap=1 and add /download
                clean = full_url.split("?")[0].rstrip("/")
                download_url = f"{clean}/download"

            filename = link_text
            if not any(filename.lower().endswith(e) for e in (".pdf", ".doc", ".docx", ".pptx")):
                filename = f"{link_text}{ext}" if ext else f"{link_text}.pdf"

            content_type = "application/pdf" if ext == ".pdf" or not ext else f"application/{ext.lstrip('.')}"
            entry = {
                "url": download_url,
                "display_url": full_url,
                "filename": filename,
                "content_type": content_type,
            }
            if module_name:
                entry["module_name"] = module_name
            if item_title:
                entry["item_title"] = item_title
            files.append(entry)

    return files


async def _canvas_api_paginate(
    client,
    url: str,
    params: dict | None = None,
    max_pages: int = 5,
) -> list[dict]:
    """Fetch all pages of a Canvas API endpoint using Link header pagination."""
    results = []
    next_url = url
    page_count = 0
    while next_url and page_count < max_pages:
        resp = await client.get(next_url, params=params if page_count == 0 else None)
        if resp.status_code != 200:
            break
        data = resp.json()
        if isinstance(data, list):
            results.extend(data)
        else:
            results.append(data)
        # Parse Link header for next page
        link_header = resp.headers.get("link", "")
        next_url = None
        for part in link_header.split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
        page_count += 1
        params = None  # params only on first request
    return results


async def _try_canvas_api(
    url: str,
    session_name: str | None = None,
) -> tuple[str, str] | None:
    """Canvas REST API extraction — get structured course data.

    Wrapper that returns (title, content) for backward compatibility.
    Calls _try_canvas_api_deep internally.
    """
    result = await _try_canvas_api_deep(url, session_name=session_name)
    if result:
        return result.title, result.content
    return None


async def _try_canvas_api_deep(
    url: str,
    session_name: str | None = None,
) -> CanvasExtraction | None:
    """Deep Canvas REST API extraction — full course content + file discovery.

    Fetches:
    1. Course info + syllabus
    2. All modules with deep item content (page bodies, not just titles)
    3. Assignments with descriptions
    4. All pages with full body content
    5. Quiz titles and questions (for study material)
    6. Discovered PDF/document file URLs from all page bodies

    Uses saved Playwright session cookies for authenticated API access.
    Ported from learning-agent-extension canvas.js API fetcher pattern.
    """
    def _clean(text: str) -> str:
        """Strip newlines and collapse whitespace in Canvas API text."""
        return re.sub(r"\s{2,}", " ", text.replace("\n", " ").replace("\r", " ")).strip()

    try:
        from services.scraper.canvas_detector import detect_canvas_url

        canvas_info = detect_canvas_url(url)
        if not canvas_info.is_canvas or not canvas_info.course_id:
            return None

        api_base = canvas_info.api_base
        course_id = canvas_info.course_id
        base_url = f"https://{canvas_info.domain}"

        import httpx

        # Load session cookies for authenticated API access (domain-filtered)
        cookies = _load_session_cookies(session_name, target_domain=canvas_info.domain) if session_name else {}
        if session_name:
            logger.info("Canvas deep API using %d cookies from session %s for %s", len(cookies), session_name, canvas_info.domain)

        all_file_urls: list[dict] = []
        seen_page_slugs: set[str] = set()
        pages_fetched = 0

        async with httpx.AsyncClient(follow_redirects=True, timeout=20, cookies=cookies) as client:
            parts: list[str] = []
            course_title = f"Course {course_id}"

            # ── 1. Course info + syllabus ──
            try:
                resp = await client.get(
                    f"{api_base}/courses/{course_id}",
                    params={"include[]": "syllabus_body"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    course_title = _clean(data.get("name", course_title))
                    parts.append(f"# {course_title}\n")
                    if data.get("syllabus_body"):
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(data["syllabus_body"], "lxml")
                        syllabus_text = soup.get_text(strip=True, separator="\n")
                        if syllabus_text:
                            parts.append(f"## Syllabus\n{syllabus_text}\n")
                        # Discover files in syllabus HTML
                        file_urls = _extract_file_urls_from_html(data["syllabus_body"], base_url)
                        all_file_urls.extend(file_urls)
                else:
                    return None
            except Exception:
                return None

            # ── 2. Modules with DEEP item content ──
            modules_found = 0
            try:
                modules = await _canvas_api_paginate(
                    client,
                    f"{api_base}/courses/{course_id}/modules",
                    params={"include[]": "items", "per_page": "100"},
                )
                if modules:
                    modules_found = len(modules)
                    parts.append("## Modules\n")
                    for mod in modules:
                        mod_name = _clean(mod.get("name", "Module"))
                        parts.append(f"### {mod_name}")
                        items = mod.get("items", [])

                        for item in items:
                            item_type = item.get("type", "")
                            item_title = _clean(item.get("title", "Item"))

                            if item_type == "Page":
                                # Deep fetch: get full page body via API
                                page_url = item.get("page_url", "")
                                if page_url and page_url not in seen_page_slugs:
                                    seen_page_slugs.add(page_url)
                                    try:
                                        page_resp = await client.get(
                                            f"{api_base}/courses/{course_id}/pages/{page_url}",
                                        )
                                        if page_resp.status_code == 200:
                                            page_data = page_resp.json()
                                            body = page_data.get("body", "")
                                            parts.append(f"#### {item_title}")
                                            if body:
                                                from bs4 import BeautifulSoup
                                                soup = BeautifulSoup(body, "lxml")
                                                page_text = soup.get_text(strip=True, separator="\n")
                                                if page_text:
                                                    parts.append(page_text)
                                                # Discover files in page HTML (with module context)
                                                file_urls = _extract_file_urls_from_html(
                                                    body, base_url,
                                                    module_name=mod_name,
                                                    item_title=item_title,
                                                )
                                                all_file_urls.extend(file_urls)
                                            pages_fetched += 1
                                    except Exception as e:
                                        logger.debug("Failed to fetch page %s: %s", page_url, e)
                                        parts.append(f"#### {item_title}")

                            elif item_type == "File":
                                # Direct file attachment in module
                                content_id = item.get("content_id")
                                if content_id:
                                    file_url = f"{base_url}/courses/{course_id}/files/{content_id}/download?verifier="
                                    all_file_urls.append({
                                        "url": file_url,
                                        "display_url": f"{base_url}/courses/{course_id}/files/{content_id}",
                                        "filename": f"{item_title}.pdf",
                                        "content_type": "application/pdf",
                                        "module_name": mod_name,
                                        "item_title": item_title,
                                    })
                                parts.append(f"#### {item_title} (File)")

                            elif item_type == "Assignment":
                                parts.append(f"#### {item_title} (Assignment)")

                            elif item_type == "Quiz":
                                parts.append(f"#### {item_title} (Quiz)")

                            elif item_type == "ExternalUrl":
                                ext_url = item.get("external_url", "")
                                parts.append(f"#### {item_title}")
                                parts.append(f"Link: {ext_url}")

                            elif item_type == "SubHeader":
                                parts.append(f"#### {item_title}")

                            else:
                                parts.append(f"#### {item_title}")

                    parts.append("")
            except Exception as e:
                logger.debug("Modules deep fetch failed: %s", e)

            # ── 3. Assignments with descriptions ──
            try:
                assignments = await _canvas_api_paginate(
                    client,
                    f"{api_base}/courses/{course_id}/assignments",
                    params={"per_page": "100"},
                )
                if assignments:
                    parts.append("## Assignments\n")
                    for a in assignments:
                        line = f"- **{a.get('name', 'Assignment')}**"
                        if a.get("due_at"):
                            line += f" (due: {a['due_at'][:10]})"
                        if a.get("points_possible"):
                            line += f" [{a['points_possible']} pts]"
                        parts.append(line)
                        desc = a.get("description")
                        if desc:
                            from bs4 import BeautifulSoup
                            soup = BeautifulSoup(desc, "lxml")
                            desc_text = soup.get_text(strip=True, separator=" ")[:500]
                            if desc_text:
                                parts.append(f"  {desc_text}")
                            # Discover files in assignment descriptions
                            file_urls = _extract_file_urls_from_html(desc, base_url)
                            all_file_urls.extend(file_urls)
                    parts.append("")
            except Exception:
                pass

            # ── 4. Pages not already fetched via modules ──
            try:
                pages = await _canvas_api_paginate(
                    client,
                    f"{api_base}/courses/{course_id}/pages",
                    params={"per_page": "50"},
                )
                unfetched = [p for p in pages if p.get("url", "") not in seen_page_slugs]
                if unfetched:
                    parts.append("## Additional Pages\n")
                    for p in unfetched[:30]:
                        slug = p.get("url", "")
                        title_text = _clean(p.get("title", "Page"))
                        seen_page_slugs.add(slug)
                        try:
                            page_resp = await client.get(
                                f"{api_base}/courses/{course_id}/pages/{slug}",
                            )
                            if page_resp.status_code == 200:
                                page_data = page_resp.json()
                                body = page_data.get("body", "")
                                parts.append(f"### {title_text}")
                                if body:
                                    from bs4 import BeautifulSoup
                                    soup = BeautifulSoup(body, "lxml")
                                    page_text = soup.get_text(strip=True, separator="\n")
                                    if page_text:
                                        parts.append(page_text)
                                    file_urls = _extract_file_urls_from_html(body, base_url)
                                    all_file_urls.extend(file_urls)
                                pages_fetched += 1
                        except Exception:
                            parts.append(f"### {title_text}")
                    parts.append("")
            except Exception:
                pass

            # ── 5. Quizzes (titles + questions → PracticeProblem-ready dicts) ──
            all_quiz_questions: list[dict] = []
            try:
                quizzes = await _canvas_api_paginate(
                    client,
                    f"{api_base}/courses/{course_id}/quizzes",
                    params={"per_page": "50"},
                )
                if quizzes:
                    parts.append("## Quizzes\n")
                    for q in quizzes:
                        q_title = _clean(q.get("title", "Quiz"))
                        q_desc = q.get("description", "")
                        q_count = q.get("question_count", 0)
                        q_points = q.get("points_possible", "")
                        parts.append(f"### {q_title}")
                        if q_points:
                            parts.append(f"Points: {q_points} | Questions: {q_count}")
                        if q_desc:
                            from bs4 import BeautifulSoup
                            soup = BeautifulSoup(q_desc, "lxml")
                            desc_text = soup.get_text(strip=True, separator="\n")
                            if desc_text:
                                parts.append(desc_text[:1000])
                        # Try to fetch quiz questions (may be restricted)
                        quiz_id = q.get("id")
                        if quiz_id:
                            try:
                                qq_resp = await client.get(
                                    f"{api_base}/courses/{course_id}/quizzes/{quiz_id}/questions",
                                    params={"per_page": "50"},
                                )
                                if qq_resp.status_code == 200:
                                    questions = qq_resp.json()
                                    for qi, question in enumerate(questions, 1):
                                        q_text = question.get("question_text", "")
                                        if q_text:
                                            from bs4 import BeautifulSoup
                                            soup = BeautifulSoup(q_text, "lxml")
                                            parts.append(f"Q{qi}: {soup.get_text(strip=True)}")
                                        answers = question.get("answers", [])
                                        for ans in answers:
                                            ans_text = ans.get("text", "") or ans.get("html", "")
                                            if ans_text:
                                                parts.append(f"  - {ans_text}")
                                        # Parse into structured PracticeProblem dict
                                        parsed = _parse_canvas_quiz_question(question, q_title)
                                        if parsed:
                                            all_quiz_questions.append(parsed)
                            except Exception:
                                pass
                    parts.append("")
            except Exception:
                pass

            # Deduplicate file URLs
            seen_file_urls: set[str] = set()
            unique_files: list[dict] = []
            for f in all_file_urls:
                display = f.get("display_url", f["url"])
                if display not in seen_file_urls:
                    seen_file_urls.add(display)
                    unique_files.append(f)

            content = "\n".join(parts)
            if len(content) >= 100:
                logger.info(
                    "Canvas deep extraction: %d chars, %d pages fetched, %d modules, %d files discovered",
                    len(content), pages_fetched, modules_found, len(unique_files),
                )
                return CanvasExtraction(
                    title=course_title,
                    content=content,
                    file_urls=unique_files,
                    pages_fetched=pages_fetched,
                    modules_found=modules_found,
                    quiz_questions=all_quiz_questions,
                )

    except ImportError:
        logger.debug("Canvas API extraction skipped: missing dependencies")
    except Exception as e:
        logger.debug("Canvas deep API extraction failed for %s: %s", url, e)

    return None


async def download_canvas_file(
    file_info: dict,
    session_name: str | None,
    target_domain: str | None,
    save_dir: str = "uploads",
) -> str | None:
    """Download a Canvas file and save to disk.

    Canvas file URLs have two forms:
    - /courses/{id}/files/{file_id}?wrap=1 → returns HTML preview page
    - /courses/{id}/files/{file_id}/download → returns actual binary file

    This function ensures we always request the /download form.
    """
    import httpx
    import os
    import hashlib

    url = file_info["url"]
    display_url = file_info.get("display_url", url)
    filename = file_info.get("filename", "file.pdf")
    filename = re.sub(r'[<>:"/\\|?*]', "_", filename)

    cookies = _load_session_cookies(session_name, target_domain=target_domain) if session_name else {}

    def _ensure_download_url(u: str) -> str:
        """Ensure a Canvas file URL uses the /download path."""
        clean = u.split("?")[0].rstrip("/")
        if clean.endswith("/download"):
            return clean
        # /courses/X/files/Y → /courses/X/files/Y/download
        if re.search(r"/files/\d+$", clean):
            return f"{clean}/download"
        return clean

    def _is_binary_content(resp) -> bool:
        """Check if the response contains binary file data (not HTML)."""
        ct = resp.headers.get("content-type", "")
        if "text/html" in ct:
            return False
        if any(t in ct for t in ("application/pdf", "application/octet", "application/vnd", "application/zip")):
            return True
        # Check magic bytes
        if resp.content[:4] == b"%PDF":
            return True
        if resp.content[:2] == b"PK":  # ZIP/PPTX/DOCX
            return True
        return len(resp.content) > 1000 and b"<html" not in resp.content[:500].lower()

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60, cookies=cookies) as client:
            # Build download URL candidates in priority order
            candidates = []
            candidates.append(_ensure_download_url(url))
            if display_url and display_url != url:
                candidates.append(_ensure_download_url(display_url))
            # Deduplicate while preserving order
            seen = set()
            unique_candidates = []
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    unique_candidates.append(c)

            for try_url in unique_candidates:
                try:
                    resp = await client.get(try_url)
                    if resp.status_code == 200 and _is_binary_content(resp) and len(resp.content) > 100:
                        os.makedirs(save_dir, exist_ok=True)
                        file_hash = hashlib.sha256(resp.content).hexdigest()[:12]
                        save_path = os.path.join(save_dir, f"{file_hash}_{filename}")
                        with open(save_path, "wb") as f:
                            f.write(resp.content)
                        logger.info("Downloaded Canvas file: %s (%d bytes)", filename, len(resp.content))
                        return save_path
                except Exception as e:
                    logger.debug("Download attempt failed for %s: %s", try_url, e)

            logger.debug("All download attempts failed for: %s", filename)
    except Exception as e:
        logger.debug("Canvas file download error for %s: %s", filename, e)

    return None


# ── Crawl4AI extraction (web + PDF + HTML) ──


async def _extract_from_url(
    url: str,
    query: str | None = None,
    session_name: str | None = None,
) -> tuple[str, str]:
    """URL extraction — multi-layer cascade with Canvas API priority.

    Fallback cascade:
    0. Canvas REST API (structured data, no HTML scraping needed)
    1. Crawl4AI (best quality — Markdown + media + metadata + BM25 filtering)
    2. httpx + clean_soup (GPT-Researcher pattern)
    3. trafilatura
    4. Playwright (existing cascade from automation.py)
    """
    # Layer 0: Canvas REST API (structured data — bypasses HTML scraping)
    result = await _try_canvas_api(url, session_name=session_name)
    if result:
        return result

    # Layer 1: Crawl4AI (with optional BM25 content filtering)
    result = await _try_crawl4ai_url(url, query=query)
    if result:
        return result

    # Layer 2: httpx + clean_soup (GPT-Researcher BeautifulSoupScraper pattern)
    result = await _try_httpx_clean_soup(url)
    if result:
        return result

    # Layer 3: trafilatura
    result = await _try_trafilatura_url(url)
    if result:
        return result

    # Layer 4: Playwright (existing browser cascade)
    result = await _try_browser_cascade(url)
    if result:
        return result

    return "", ""


async def _try_crawl4ai_url(url: str, query: str | None = None) -> tuple[str, str] | None:
    """Layer 1: Crawl4AI — handles web pages and PDF URLs uniformly.

    When query is provided, enables BM25 content filtering to extract only
    query-relevant sections from noisy web pages (Crawl4AI BM25ContentFilter).
    """
    try:
        from crawl4ai import AsyncWebCrawler

        async with AsyncWebCrawler() as crawler:
            config = _build_crawl4ai_config(query)
            result = await crawler.arun(url=url, config=config)
            if result.success:
                md = result.markdown
                # Prefer BM25-filtered markdown when query was provided
                raw = ""
                if query and hasattr(md, "fit_markdown") and md.fit_markdown:
                    raw = md.fit_markdown
                if not raw:
                    raw = md.raw_markdown if hasattr(md, "raw_markdown") else str(md)
                if len(raw) >= 100:
                    title = url
                    if result.metadata and isinstance(result.metadata, dict):
                        title = result.metadata.get("title", url) or url
                    return title, raw
    except ImportError:
        logger.debug("crawl4ai not installed, skipping Crawl4AI layer")
    except Exception as e:
        logger.debug(f"Crawl4AI failed for {url}: {e}")
    return None


async def _try_httpx_clean_soup(url: str) -> tuple[str, str] | None:
    """Layer 2: httpx fetch + GPT-Researcher clean_soup() HTML cleaning."""
    try:
        import httpx
        from bs4 import BeautifulSoup

        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            html = resp.text

        soup = BeautifulSoup(html, "lxml")
        soup = clean_soup(soup)
        title = extract_title(soup)
        content = get_text_from_soup(soup)

        if len(content) >= 100:
            return title or url, content
    except ImportError:
        logger.debug("bs4/lxml not installed, skipping httpx+clean_soup layer")
    except Exception as e:
        logger.debug(f"httpx+clean_soup failed for {url}: {e}")
    return None


async def _try_trafilatura_url(url: str) -> tuple[str, str] | None:
    """Layer 3: trafilatura fallback (runs in thread to avoid blocking loop)."""
    return await asyncio.to_thread(_try_trafilatura_url_sync, url)


def _try_trafilatura_url_sync(url: str) -> tuple[str, str] | None:
    """Synchronous trafilatura fallback implementation."""
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        content = trafilatura.extract(
            downloaded,
            include_links=True,
            include_formatting=True,
            include_tables=True,
            output_format="txt",
        )
        if content and len(content) >= 100:
            metadata = trafilatura.extract_metadata(downloaded)
            title = metadata.title if metadata and metadata.title else url
            return title, content
    except ImportError:
        logger.debug("trafilatura not installed, skipping trafilatura layer")
    except Exception as e:
        logger.debug(f"trafilatura failed for {url}: {e}")
    return None


async def _try_browser_cascade(url: str) -> tuple[str, str] | None:
    """Layer 4: Playwright browser cascade (existing automation.py)."""
    try:
        from services.browser.automation import cascade_fetch
        from services.parser.url import extract_text_from_html

        html = await cascade_fetch(url)
        if html:
            text = extract_text_from_html(html)
            if text and len(text) >= 50:
                return url, text
    except Exception as e:
        logger.debug(f"Browser cascade failed for {url}: {e}")
    return None


# ── Crawl4AI local file extraction ──


async def _extract_local_with_crawl4ai(file_path: str) -> tuple[str, str]:
    """Extract content from local PDF/HTML via Crawl4AI file:// protocol.

    Falls back to legacy extractors if Crawl4AI is unavailable.
    """
    abs_path = str(Path(file_path).resolve())
    file_url = f"file://{abs_path}"

    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=file_url, config=CrawlerRunConfig())
            if result.success:
                md = result.markdown
                raw = md.raw_markdown if hasattr(md, "raw_markdown") else str(md)
                if raw:
                    title = ""
                    if result.metadata and isinstance(result.metadata, dict):
                        title = result.metadata.get("title", "") or ""
                    return title or Path(file_path).stem, raw
    except ImportError:
        logger.debug("crawl4ai not installed, falling back to legacy extractors")
    except Exception as e:
        logger.debug(f"Crawl4AI local extraction failed for {file_path}: {e}")

    # Fallback for PDF
    ext = Path(file_path).suffix.lstrip(".").lower()
    if ext == "pdf":
        return await asyncio.to_thread(_extract_pdf_fallback, file_path)

    # Fallback for HTML
    if ext in ("html", "htm"):
        return await asyncio.to_thread(_extract_html_fallback, file_path)

    return Path(file_path).stem, ""


def _extract_pdf_fallback(file_path: str) -> tuple[str, str]:
    """PDF fallback: Marker → pypdf."""
    # Try Marker
    try:
        from marker.converters.pdf import PdfConverter

        converter = PdfConverter(artifact_dict=_get_marker_models())
        rendered = converter(file_path)
        return Path(file_path).stem, rendered.markdown
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"Marker PDF extraction failed: {e}")

    # Try pypdf
    try:
        import pypdf

        reader = pypdf.PdfReader(file_path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return Path(file_path).stem, text
    except Exception as e:
        logger.debug(f"pypdf extraction failed: {e}")

    return Path(file_path).stem, ""


def _extract_html_fallback(file_path: str) -> tuple[str, str]:
    """HTML fallback: trafilatura → raw read."""
    try:
        import trafilatura

        with open(file_path) as f:
            html = f.read()
        content = trafilatura.extract(html, include_tables=True) or ""
        if content:
            return Path(file_path).stem, content
    except Exception:
        pass

    # Raw text fallback
    try:
        return Path(file_path).stem, Path(file_path).read_text(errors="ignore")
    except Exception:
        return Path(file_path).stem, ""


# ── GPT-Researcher loader_dict (Office formats) ──


def _extract_with_loader_dict(file_path: str, ext: str) -> tuple[str, str]:
    """DOCX/PPTX/XLSX/CSV extraction using GPT-Researcher's loader_dict pattern.

    Reference: gpt_researcher/document/document.py L66-78
    """
    try:
        from langchain_community.document_loaders import (
            UnstructuredCSVLoader,
            UnstructuredExcelLoader,
            UnstructuredPowerPointLoader,
            UnstructuredWordDocumentLoader,
        )

        loader_map = {
            "doc": lambda fp: UnstructuredWordDocumentLoader(fp),
            "docx": lambda fp: UnstructuredWordDocumentLoader(fp),
            "pptx": lambda fp: UnstructuredPowerPointLoader(fp),
            "csv": lambda fp: UnstructuredCSVLoader(fp, mode="elements"),
            "xls": lambda fp: UnstructuredExcelLoader(fp, mode="elements"),
            "xlsx": lambda fp: UnstructuredExcelLoader(fp, mode="elements"),
        }

        factory = loader_map.get(ext)
        if not factory:
            return Path(file_path).stem, ""

        loader = factory(file_path)
        docs = loader.load()
        content = "\n\n".join(doc.page_content for doc in docs if doc.page_content)
        return Path(file_path).stem, content

    except ImportError:
        logger.warning(
            "langchain-community/unstructured not installed. "
            "Falling back to basic extraction for %s files. "
            "Install with: pip install langchain-community unstructured",
            ext,
        )
        return _extract_office_fallback(file_path, ext)
    except Exception as e:
        logger.warning(f"loader_dict extraction failed for {file_path}: {e}")
        return _extract_office_fallback(file_path, ext)


def _extract_office_fallback(file_path: str, ext: str) -> tuple[str, str]:
    """Basic fallback for Office formats when Unstructured is unavailable."""
    if ext in ("doc", "docx"):
        try:
            from docx import Document

            doc = Document(file_path)
            content = "\n\n".join(p.text for p in doc.paragraphs if p.text)
            return Path(file_path).stem, content
        except Exception:
            pass

    if ext in ("pptx",):
        try:
            from pptx import Presentation

            prs = Presentation(file_path)
            texts = []
            for slide_num, slide in enumerate(prs.slides, 1):
                texts.append(f"## Slide {slide_num}")
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        texts.append(shape.text_frame.text)
            return Path(file_path).stem, "\n\n".join(texts)
        except Exception:
            pass

    return Path(file_path).stem, ""


# ── Plain text extraction ──


def _extract_plain_text(file_path: str) -> tuple[str, str]:
    """Direct text read for .txt, .md, .rst, and unknown files."""
    try:
        content = Path(file_path).read_text(errors="ignore")
        return Path(file_path).stem, content
    except Exception:
        return Path(file_path).stem, ""


def _get_marker_models() -> dict:
    """Lazy-load Marker models once for local PDF fallback path."""
    global _marker_models
    if _marker_models is None:
        from marker.models import create_model_dict

        _marker_models = create_model_dict()
    return _marker_models


# ── HTML cleaning utilities (GPT-Researcher scraper/utils.py L94-132) ──


def clean_soup(soup):
    """Clean HTML by removing unwanted tags.

    Ported from GPT-Researcher scraper/utils.py clean_soup().
    """
    import bs4

    for tag in soup.find_all(
        ["script", "style", "footer", "header", "nav", "menu", "sidebar", "svg"]
    ):
        tag.decompose()

    disallowed_class_set = {"nav", "menu", "sidebar", "footer"}

    def has_disallowed_class(elem):
        if not isinstance(elem, bs4.Tag):
            return False
        return any(cls in disallowed_class_set for cls in elem.get("class", []))

    for tag in soup.find_all(has_disallowed_class):
        tag.decompose()

    return soup


def clean_soup_canvas_aware(soup):
    """Canvas-aware HTML cleaner that preserves course content containers.

    Canvas LMS puts content inside elements that generic cleaners strip out
    (e.g. nav-like sidebars, module containers). This cleaner only removes
    truly non-content elements while preserving Canvas-specific structure.
    """
    # Only remove script, style, and SVG — preserve everything else
    for tag in soup.find_all(["script", "style", "svg", "noscript"]):
        tag.decompose()

    # Remove Canvas chrome (global nav, breadcrumbs, footer) but keep content
    canvas_chrome_ids = [
        "header", "menu", "left-side", "breadcrumbs",
        "flash_message_holder", "footer",
    ]
    for chrome_id in canvas_chrome_ids:
        elem = soup.find(id=chrome_id)
        if elem:
            elem.decompose()

    # Try to extract just the main content area if it exists
    content_area = (
        soup.find(id="content")
        or soup.find(id="wiki_page_show")
        or soup.find(class_="ic-app-main-content")
        or soup.find(role="main")
    )
    if content_area:
        return content_area

    return soup


def extract_title(soup) -> str:
    """Extract title from BeautifulSoup object.

    Ported from GPT-Researcher scraper/utils.py extract_title().
    """
    return soup.title.string if soup.title else ""


def get_text_from_soup(soup) -> str:
    """Get clean text from BeautifulSoup object.

    Ported from GPT-Researcher scraper/utils.py get_text_from_soup().
    """
    text = soup.get_text(strip=True, separator="\n")
    # Collapse runs of 3+ newlines to double newline (paragraph break)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse runs of spaces (but preserve newlines for structure)
    text = re.sub(r"[^\S\n]{2,}", " ", text)
    return text.strip()
