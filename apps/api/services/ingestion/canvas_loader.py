"""Canvas LMS content extraction via REST API.

Thin facade that re-exports all public symbols from the Canvas sub-modules
so that existing ``from services.ingestion.canvas_loader import X`` statements
continue to work unchanged.

Sub-modules:
- canvas_http:    session cookies, rate-limited requests, pagination, text utils
- canvas_parser:  CanvasExtraction dataclass, quiz question parsing, file URL extraction
- canvas_download: authenticated file download
- canvas_loader_fetch: per-endpoint fetch helpers (course, modules, assignments, pages, quizzes)

The orchestrator functions (_try_canvas_api, _try_canvas_api_deep) live here.
"""

import logging

import httpx

from services.ingestion.canvas_http import (  # noqa: F401
    _load_session_cookies,
    CanvasAuthExpiredError,
    _canvas_api_request_with_backoff,
    _canvas_api_paginate,
    _canvas_clean_text,
    _html_to_text,
)
from services.ingestion.canvas_parser import (  # noqa: F401
    CanvasExtraction,
    _parse_canvas_quiz_question,
    _extract_file_urls_from_html,
)
from services.ingestion.canvas_download import (  # noqa: F401
    download_canvas_file,
)
from services.ingestion.canvas_loader_fetch import (  # noqa: F401
    _canvas_fetch_course_info,
    _canvas_fetch_modules,
    _canvas_fetch_assignments,
    _canvas_fetch_additional_pages,
    _canvas_fetch_quizzes,
)

logger = logging.getLogger(__name__)


async def _try_canvas_api(
    url: str,
    session_name: str | None = None,
) -> tuple[str, str] | None:
    """Canvas REST API extraction -- get structured course data.

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
    """Deep Canvas REST API extraction -- full course content + file discovery."""
    try:
        from services.scraper.canvas_detector import detect_canvas_url

        canvas_info = detect_canvas_url(url)
        if not canvas_info.is_canvas or not canvas_info.course_id:
            return None

        api_base = canvas_info.api_base
        course_id = canvas_info.course_id
        base_url = f"https://{canvas_info.domain}"

        cookies = _load_session_cookies(session_name, target_domain=canvas_info.domain) if session_name else {}
        if session_name:
            if cookies:
                logger.info(
                    "Canvas deep API using %d cookies from session %s for %s",
                    len(cookies), session_name, canvas_info.domain,
                )
            else:
                logger.warning(
                    "Canvas deep API: 0 cookies loaded from session '%s' for %s — "
                    "API requests will be unauthenticated and likely return 401",
                    session_name, canvas_info.domain,
                )

        all_file_urls: list[dict] = []
        seen_page_slugs: set[str] = set()

        async with httpx.AsyncClient(follow_redirects=True, timeout=20, cookies=cookies) as client:
            # 1. Course info + syllabus
            try:
                course_result = await _canvas_fetch_course_info(
                    client, api_base, course_id, base_url, canvas_info.domain,
                )
            except CanvasAuthExpiredError:
                raise
            except (httpx.HTTPError, OSError, KeyError, ValueError) as e:
                logger.exception("Canvas course info fetch failed for %s", url)
                return None
            if not course_result:
                return None
            course_title, parts, syllabus_files = course_result
            all_file_urls.extend(syllabus_files)

            # 2. Modules with deep item content
            try:
                modules_found, mod_pages, mod_parts, mod_files = await _canvas_fetch_modules(
                    client, api_base, course_id, base_url, seen_page_slugs,
                )
                parts.extend(mod_parts)
                all_file_urls.extend(mod_files)
            except (httpx.HTTPError, OSError, KeyError, ValueError) as e:
                logger.exception("Modules deep fetch failed")
                modules_found, mod_pages = 0, 0

            # 3. Assignments with descriptions
            try:
                all_assignments_data, assign_parts, assign_files = await _canvas_fetch_assignments(
                    client, api_base, course_id, base_url,
                )
                parts.extend(assign_parts)
                all_file_urls.extend(assign_files)
            except (httpx.HTTPError, OSError, KeyError, ValueError) as e:
                logger.exception("Canvas assignments fetch failed")
                all_assignments_data = []

            # 4. Additional pages
            try:
                extra_pages, page_parts, page_files = await _canvas_fetch_additional_pages(
                    client, api_base, course_id, base_url, seen_page_slugs,
                )
                parts.extend(page_parts)
                all_file_urls.extend(page_files)
            except (httpx.HTTPError, OSError, KeyError, ValueError) as e:
                logger.exception("Canvas additional pages fetch failed")
                extra_pages = 0

            # 5. Quizzes
            try:
                all_quiz_questions, quiz_parts = await _canvas_fetch_quizzes(
                    client, api_base, course_id,
                )
                parts.extend(quiz_parts)
            except (httpx.HTTPError, OSError, KeyError, ValueError) as e:
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
        raise
    except (httpx.HTTPError, OSError, KeyError, ValueError) as e:
        logger.warning("Canvas deep API extraction failed for %s: %s", url, e)

    return None
