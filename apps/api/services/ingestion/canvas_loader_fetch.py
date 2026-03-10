"""Canvas API data fetching helpers.

Individual fetch functions for Canvas REST API endpoints:
- Course info + syllabus
- Modules with deep item content
- Assignments with descriptions
- Additional pages
- Quizzes with questions

Extracted from canvas_loader.py.
"""

import logging

import httpx

from services.ingestion.canvas_http import (
    _canvas_api_request_with_backoff,
    _canvas_api_paginate,
    _canvas_clean_text,
    _html_to_text,
    CanvasAuthExpiredError,
)
from services.ingestion.canvas_parser import (
    _extract_file_urls_from_html,
    _parse_canvas_quiz_question,
)

logger = logging.getLogger(__name__)


async def _canvas_fetch_course_info(
    client, api_base: str, course_id: str, base_url: str, domain: str,
) -> tuple[str, list[str], list[dict]] | None:
    """Fetch course info + syllabus. Returns (title, parts, file_urls) or None."""
    resp = await _canvas_api_request_with_backoff(
        client, f"{api_base}/courses/{course_id}", params={"include[]": "syllabus_body"},
    )
    if resp.status_code == 401:
        raise CanvasAuthExpiredError(
            f"Canvas API returned 401 for {domain}. Session cookies are expired -- please re-login to Canvas."
        )
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


async def _canvas_fetch_modules(
    client, api_base: str, course_id: str, base_url: str, seen_page_slugs: set,
) -> tuple[int, int, list[str], list[dict]]:
    """Fetch modules with deep item content. Returns (modules_found, pages_fetched, parts, file_urls)."""
    parts: list[str] = []
    file_urls: list[dict] = []
    pages_fetched = 0
    modules = await _canvas_api_paginate(
        client, f"{api_base}/courses/{course_id}/modules",
        params={"include[]": "items", "per_page": "100"},
    )
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
                        page_resp = await _canvas_api_request_with_backoff(
                            client, f"{api_base}/courses/{course_id}/pages/{page_url}",
                        )
                        if page_resp.status_code == 200:
                            body = page_resp.json().get("body", "")
                            parts.append(f"#### {item_title}")
                            if body:
                                page_text = _html_to_text(body)
                                if page_text:
                                    parts.append(page_text)
                                file_urls.extend(
                                    _extract_file_urls_from_html(
                                        body, base_url, module_name=mod_name, item_title=item_title,
                                    )
                                )
                            pages_fetched += 1
                    except (httpx.HTTPError, OSError, KeyError, ValueError) as e:
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


async def _canvas_fetch_assignments(
    client, api_base: str, course_id: str, base_url: str,
) -> tuple[list[dict], list[str], list[dict]]:
    """Fetch assignments with descriptions. Returns (assignments_data, parts, file_urls)."""
    parts: list[str] = []
    file_urls: list[dict] = []
    assignments = await _canvas_api_paginate(
        client, f"{api_base}/courses/{course_id}/assignments", params={"per_page": "100"},
    )
    if not assignments:
        return [], parts, file_urls
    assignments_data = [
        {
            "name": a.get("name"),
            "due_at": a.get("due_at"),
            "points_possible": a.get("points_possible"),
            "canvas_id": a.get("id"),
        }
        for a in assignments
        if a.get("name")
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


async def _canvas_fetch_additional_pages(
    client, api_base: str, course_id: str, base_url: str, seen_page_slugs: set,
) -> tuple[int, list[str], list[dict]]:
    """Fetch pages not already fetched via modules. Returns (pages_fetched, parts, file_urls)."""
    parts: list[str] = []
    file_urls: list[dict] = []
    pages_fetched = 0
    pages = await _canvas_api_paginate(
        client, f"{api_base}/courses/{course_id}/pages", params={"per_page": "50"},
    )
    unfetched = [p for p in pages if p.get("url", "") not in seen_page_slugs]
    if not unfetched:
        return 0, parts, file_urls
    parts.append("## Additional Pages\n")
    for p in unfetched[:30]:
        slug = p.get("url", "")
        title_text = _canvas_clean_text(p.get("title", "Page"))
        seen_page_slugs.add(slug)
        try:
            page_resp = await _canvas_api_request_with_backoff(
                client, f"{api_base}/courses/{course_id}/pages/{slug}",
            )
            if page_resp.status_code == 200:
                body = page_resp.json().get("body", "")
                parts.append(f"### {title_text}")
                if body:
                    page_text = _html_to_text(body)
                    if page_text:
                        parts.append(page_text)
                    file_urls.extend(_extract_file_urls_from_html(body, base_url))
                pages_fetched += 1
        except (httpx.HTTPError, OSError, KeyError, ValueError) as e:
            logger.warning("Failed to fetch Canvas additional page %s: %s", slug, e)
            parts.append(f"### {title_text}")
    parts.append("")
    return pages_fetched, parts, file_urls


async def _canvas_fetch_quizzes(
    client, api_base: str, course_id: str,
) -> tuple[list[dict], list[str]]:
    """Fetch quizzes with questions. Returns (quiz_questions, parts)."""
    parts: list[str] = []
    quiz_questions: list[dict] = []
    quizzes = await _canvas_api_paginate(
        client, f"{api_base}/courses/{course_id}/quizzes", params={"per_page": "50"},
    )
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
                qq_resp = await _canvas_api_request_with_backoff(
                    client,
                    f"{api_base}/courses/{course_id}/quizzes/{quiz_id}/questions",
                    params={"per_page": "50"},
                )
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
            except (httpx.HTTPError, OSError, KeyError, ValueError) as e:
                logger.warning(
                    "Failed to fetch Canvas quiz questions for quiz %s: %s", quiz_id, e,
                )
    parts.append("")
    return quiz_questions, parts
