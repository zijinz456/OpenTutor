"""Canvas LMS content extraction via REST API.

Extracted from document_loader.py — Canvas-specific functions for
authenticated API access, course content fetching, file discovery,
and quiz question parsing.

Uses saved Playwright session cookies for authenticated Canvas API access.
"""

import logging
import re
import asyncio
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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

        state_path = SessionManager.state_file(session_name)
        if not state_path.exists():
            return {}

        state = SessionManager._load_state_json(state_path)
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
        logger.warning("Failed to load session cookies for %s: %s", session_name, e)
        return {}


class CanvasAuthExpiredError(Exception):
    """Raised when Canvas API returns 401 — session cookies are stale."""
    pass


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
    assignments_data: list[dict] = field(default_factory=list)
    """Raw Canvas API assignment objects with due_at, name, points_possible, etc."""


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
    from pathlib import Path

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


# Canvas API concurrency limiter — prevents rate limit hits (700 req/10min)
_canvas_api_semaphore = asyncio.Semaphore(5)


async def _canvas_api_request_with_backoff(client, url: str, params: dict | None = None, max_retries: int = 3):
    """Make a Canvas API request with exponential backoff on rate limits."""
    async with _canvas_api_semaphore:
        for attempt in range(max_retries):
            resp = await client.get(url, params=params)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                logger.warning("Canvas API rate limited, retrying after %.1fs (attempt %d/%d)", retry_after, attempt + 1, max_retries)
                await asyncio.sleep(min(retry_after, 30))
                continue
            return resp
        return resp  # Return last response even if still 429


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
        resp = await _canvas_api_request_with_backoff(client, next_url, params=params if page_count == 0 else None)
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


def _canvas_clean_text(text: str) -> str:
    """Strip newlines and collapse whitespace in Canvas API text."""
    return re.sub(r"\s{2,}", " ", text.replace("\n", " ").replace("\r", " ")).strip()


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text using BeautifulSoup."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(strip=True, separator="\n")


async def _canvas_fetch_course_info(client, api_base: str, course_id: str, base_url: str, domain: str) -> tuple[str, list[str], list[dict]] | None:
    """Fetch course info + syllabus. Returns (title, parts, file_urls) or None."""
    resp = await _canvas_api_request_with_backoff(client, f"{api_base}/courses/{course_id}", params={"include[]": "syllabus_body"})
    if resp.status_code == 401:
        raise CanvasAuthExpiredError(f"Canvas API returned 401 for {domain}. Session cookies are expired — please re-login to Canvas.")
    if resp.status_code != 200:
        return None
    data = resp.json()
    title = _canvas_clean_text(data.get("name", f"Course {course_id}"))
    parts = [f"# {title}\n"]
    file_urls = []
    if data.get("syllabus_body"):
        syllabus_text = _html_to_text(data["syllabus_body"])
        if syllabus_text:
            parts.append(f"## Syllabus\n{syllabus_text}\n")
        file_urls.extend(_extract_file_urls_from_html(data["syllabus_body"], base_url))
    return title, parts, file_urls


async def _canvas_fetch_modules(client, api_base: str, course_id: str, base_url: str, seen_page_slugs: set) -> tuple[int, int, list[str], list[dict]]:
    """Fetch modules with deep item content. Returns (modules_found, pages_fetched, parts, file_urls)."""
    parts: list[str] = []
    file_urls: list[dict] = []
    pages_fetched = 0
    modules = await _canvas_api_paginate(client, f"{api_base}/courses/{course_id}/modules", params={"include[]": "items", "per_page": "100"})
    if not modules:
        return 0, 0, parts, file_urls

    parts.append("## Modules\n")
    for mod in modules:
        mod_name = _canvas_clean_text(mod.get("name", "Module"))
        parts.append(f"### {mod_name}")
        for item in mod.get("items", []):
            item_type = item.get("type", "")
            item_title = _canvas_clean_text(item.get("title", "Item"))
            if item_type == "Page":
                page_url = item.get("page_url", "")
                if page_url and page_url not in seen_page_slugs:
                    seen_page_slugs.add(page_url)
                    try:
                        page_resp = await _canvas_api_request_with_backoff(client, f"{api_base}/courses/{course_id}/pages/{page_url}")
                        if page_resp.status_code == 200:
                            body = page_resp.json().get("body", "")
                            parts.append(f"#### {item_title}")
                            if body:
                                page_text = _html_to_text(body)
                                if page_text:
                                    parts.append(page_text)
                                file_urls.extend(_extract_file_urls_from_html(body, base_url, module_name=mod_name, item_title=item_title))
                            pages_fetched += 1
                    except Exception as e:
                        logger.warning("Failed to fetch page %s: %s", page_url, e)
                        parts.append(f"#### {item_title}")
            elif item_type == "File":
                content_id = item.get("content_id")
                if content_id:
                    file_urls.append({
                        "url": f"{base_url}/courses/{course_id}/files/{content_id}/download?verifier=",
                        "display_url": f"{base_url}/courses/{course_id}/files/{content_id}",
                        "filename": f"{item_title}.pdf",
                        "content_type": "application/pdf",
                        "module_name": mod_name,
                        "item_title": item_title,
                    })
                parts.append(f"#### {item_title} (File)")
            elif item_type == "ExternalUrl":
                parts.append(f"#### {item_title}")
                parts.append(f"Link: {item.get('external_url', '')}")
            elif item_type in ("Assignment", "Quiz"):
                parts.append(f"#### {item_title} ({item_type})")
            else:
                parts.append(f"#### {item_title}")
    parts.append("")
    return len(modules), pages_fetched, parts, file_urls


async def _canvas_fetch_assignments(client, api_base: str, course_id: str, base_url: str) -> tuple[list[dict], list[str], list[dict]]:
    """Fetch assignments with descriptions. Returns (assignments_data, parts, file_urls)."""
    parts: list[str] = []
    file_urls: list[dict] = []
    assignments = await _canvas_api_paginate(client, f"{api_base}/courses/{course_id}/assignments", params={"per_page": "100"})
    if not assignments:
        return [], parts, file_urls
    assignments_data = [
        {"name": a.get("name"), "due_at": a.get("due_at"), "points_possible": a.get("points_possible"), "canvas_id": a.get("id")}
        for a in assignments if a.get("name")
    ]
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
            desc_text = _html_to_text(desc)[:500]
            if desc_text:
                parts.append(f"  {desc_text}")
            file_urls.extend(_extract_file_urls_from_html(desc, base_url))
    parts.append("")
    return assignments_data, parts, file_urls


async def _canvas_fetch_additional_pages(client, api_base: str, course_id: str, base_url: str, seen_page_slugs: set) -> tuple[int, list[str], list[dict]]:
    """Fetch pages not already fetched via modules. Returns (pages_fetched, parts, file_urls)."""
    parts: list[str] = []
    file_urls: list[dict] = []
    pages_fetched = 0
    pages = await _canvas_api_paginate(client, f"{api_base}/courses/{course_id}/pages", params={"per_page": "50"})
    unfetched = [p for p in pages if p.get("url", "") not in seen_page_slugs]
    if not unfetched:
        return 0, parts, file_urls
    parts.append("## Additional Pages\n")
    for p in unfetched[:30]:
        slug = p.get("url", "")
        title_text = _canvas_clean_text(p.get("title", "Page"))
        seen_page_slugs.add(slug)
        try:
            page_resp = await _canvas_api_request_with_backoff(client, f"{api_base}/courses/{course_id}/pages/{slug}")
            if page_resp.status_code == 200:
                body = page_resp.json().get("body", "")
                parts.append(f"### {title_text}")
                if body:
                    page_text = _html_to_text(body)
                    if page_text:
                        parts.append(page_text)
                    file_urls.extend(_extract_file_urls_from_html(body, base_url))
                pages_fetched += 1
        except Exception as e:
            logger.warning("Failed to fetch Canvas additional page %s: %s", slug, e)
            parts.append(f"### {title_text}")
    parts.append("")
    return pages_fetched, parts, file_urls


async def _canvas_fetch_quizzes(client, api_base: str, course_id: str) -> tuple[list[dict], list[str]]:
    """Fetch quizzes with questions. Returns (quiz_questions, parts)."""
    parts: list[str] = []
    quiz_questions: list[dict] = []
    quizzes = await _canvas_api_paginate(client, f"{api_base}/courses/{course_id}/quizzes", params={"per_page": "50"})
    if not quizzes:
        return quiz_questions, parts
    parts.append("## Quizzes\n")
    for q in quizzes:
        q_title = _canvas_clean_text(q.get("title", "Quiz"))
        q_desc = q.get("description", "")
        q_points = q.get("points_possible", "")
        parts.append(f"### {q_title}")
        if q_points:
            parts.append(f"Points: {q_points} | Questions: {q.get('question_count', 0)}")
        if q_desc:
            desc_text = _html_to_text(q_desc)
            if desc_text:
                parts.append(desc_text[:1000])
        quiz_id = q.get("id")
        if quiz_id:
            try:
                qq_resp = await _canvas_api_request_with_backoff(client, f"{api_base}/courses/{course_id}/quizzes/{quiz_id}/questions", params={"per_page": "50"})
                if qq_resp.status_code == 200:
                    for qi, question in enumerate(qq_resp.json(), 1):
                        q_text = question.get("question_text", "")
                        if q_text:
                            parts.append(f"Q{qi}: {_html_to_text(q_text)}")
                        for ans in question.get("answers", []):
                            ans_text = ans.get("text", "") or ans.get("html", "")
                            if ans_text:
                                parts.append(f"  - {ans_text}")
                        parsed = _parse_canvas_quiz_question(question, q_title)
                        if parsed:
                            quiz_questions.append(parsed)
            except Exception as e:
                logger.warning("Failed to fetch Canvas quiz questions for quiz %s: %s", quiz_id, e)
    parts.append("")
    return quiz_questions, parts


async def _try_canvas_api_deep(
    url: str,
    session_name: str | None = None,
) -> CanvasExtraction | None:
    """Deep Canvas REST API extraction — full course content + file discovery.

    Fetches course info, modules, assignments, pages, and quizzes via
    extracted helper functions. Uses saved Playwright session cookies
    for authenticated API access.
    """
    try:
        from services.scraper.canvas_detector import detect_canvas_url

        canvas_info = detect_canvas_url(url)
        if not canvas_info.is_canvas or not canvas_info.course_id:
            return None

        api_base = canvas_info.api_base
        course_id = canvas_info.course_id
        base_url = f"https://{canvas_info.domain}"

        import httpx

        cookies = _load_session_cookies(session_name, target_domain=canvas_info.domain) if session_name else {}
        if session_name:
            logger.info("Canvas deep API using %d cookies from session %s for %s", len(cookies), session_name, canvas_info.domain)

        all_file_urls: list[dict] = []
        seen_page_slugs: set[str] = set()

        async with httpx.AsyncClient(follow_redirects=True, timeout=20, cookies=cookies) as client:
            # 1. Course info + syllabus
            try:
                course_result = await _canvas_fetch_course_info(client, api_base, course_id, base_url, canvas_info.domain)
            except CanvasAuthExpiredError:
                raise
            except Exception as e:
                logger.exception("Canvas course info fetch failed for %s", url)
                return None
            if not course_result:
                return None
            course_title, parts, syllabus_files = course_result
            all_file_urls.extend(syllabus_files)

            # 2. Modules with deep item content
            try:
                modules_found, mod_pages, mod_parts, mod_files = await _canvas_fetch_modules(client, api_base, course_id, base_url, seen_page_slugs)
                parts.extend(mod_parts)
                all_file_urls.extend(mod_files)
            except Exception as e:
                logger.exception("Modules deep fetch failed")
                modules_found, mod_pages = 0, 0

            # 3. Assignments with descriptions
            try:
                all_assignments_data, assign_parts, assign_files = await _canvas_fetch_assignments(client, api_base, course_id, base_url)
                parts.extend(assign_parts)
                all_file_urls.extend(assign_files)
            except Exception as e:
                logger.exception("Canvas assignments fetch failed")
                all_assignments_data = []

            # 4. Additional pages
            try:
                extra_pages, page_parts, page_files = await _canvas_fetch_additional_pages(client, api_base, course_id, base_url, seen_page_slugs)
                parts.extend(page_parts)
                all_file_urls.extend(page_files)
            except Exception as e:
                logger.exception("Canvas additional pages fetch failed")
                extra_pages = 0

            # 5. Quizzes
            try:
                all_quiz_questions, quiz_parts = await _canvas_fetch_quizzes(client, api_base, course_id)
                parts.extend(quiz_parts)
            except Exception as e:
                logger.exception("Canvas quizzes fetch failed")
                all_quiz_questions = []

            pages_fetched = mod_pages + extra_pages

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
                    assignments_data=all_assignments_data,
                )

    except ImportError:
        logger.debug("Canvas API extraction skipped: missing dependencies")
    except CanvasAuthExpiredError:
        raise  # Let auth errors propagate to caller
    except Exception as e:
        logger.warning("Canvas deep API extraction failed for %s: %s", url, e)

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
                    logger.warning("Canvas download attempt failed for %s: %s", try_url, e)

            logger.warning("All download attempts failed for: %s", filename)
    except Exception as e:
        logger.exception("Canvas file download error for %s", filename)

    return None
