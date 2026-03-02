"""Canvas LMS URL detection and metadata extraction.

Borrowed from learning-agent-extension's URL detection patterns and enhanced
for server-side use. Detects Canvas LMS URLs and extracts structured metadata
(base URL, course ID, page type) for auth-aware scraping.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# Canvas URL patterns — ported from learning-agent-extension service-worker.js
_CANVAS_URL_PATTERNS = [
    re.compile(r"^https?://canvas\.[^/]*\.edu", re.IGNORECASE),
    re.compile(r"^https?://[^/]*\.edu/.*/canvas", re.IGNORECASE),
    re.compile(r"^https?://[^/]*\.instructure\.com", re.IGNORECASE),
    re.compile(r"^https?://[^/]*\.canvaslms\.com", re.IGNORECASE),
    # Also match direct LMS subdomains like canvas.lms.unimelb.edu.au
    re.compile(r"^https?://canvas\.lms\.[^/]+\.edu", re.IGNORECASE),
]

# Canvas page type detection from path — ported from canvas_parser.py
_PAGE_TYPE_PATTERNS = [
    (re.compile(r"/courses/\d+/assignments(?:/\d+)?"), "assignments"),
    (re.compile(r"/courses/\d+/discussion_topics"), "discussions"),
    (re.compile(r"/courses/\d+/quizzes"), "quizzes"),
    (re.compile(r"/courses/\d+/modules"), "modules"),
    (re.compile(r"/courses/\d+/pages"), "pages"),
    (re.compile(r"/courses/\d+/files"), "files"),
    (re.compile(r"/courses/\d+/syllabus"), "syllabus"),
    (re.compile(r"/courses/\d+/announcements"), "announcements"),
    (re.compile(r"/courses/\d+/grades"), "grades"),
    (re.compile(r"/courses/\d+/?$"), "course_home"),
    (re.compile(r"/courses/?$"), "course_list"),
    (re.compile(r"/dashboard"), "dashboard"),
]

_COURSE_ID_PATTERN = re.compile(r"/courses/(\d+)")


@dataclass
class CanvasURLInfo:
    """Structured metadata extracted from a Canvas URL."""

    is_canvas: bool
    base_url: str = ""  # e.g. https://canvas.lms.unimelb.edu.au
    domain: str = ""  # e.g. canvas.lms.unimelb.edu.au
    course_id: str = ""  # e.g. "250590"
    page_type: str = ""  # e.g. "course_home", "assignments"
    friendly_name: str = ""  # e.g. "Canvas Course 250590"
    api_base: str = ""  # e.g. https://canvas.lms.unimelb.edu.au/api/v1


def detect_canvas_url(url: str) -> CanvasURLInfo:
    """Detect if a URL is a Canvas LMS URL and extract metadata.

    Returns CanvasURLInfo with is_canvas=False if not a Canvas URL.
    """
    if not url:
        return CanvasURLInfo(is_canvas=False)

    is_canvas = any(pattern.search(url) for pattern in _CANVAS_URL_PATTERNS)
    if not is_canvas:
        return CanvasURLInfo(is_canvas=False)

    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc

    # Extract course ID
    course_match = _COURSE_ID_PATTERN.search(parsed.path)
    course_id = course_match.group(1) if course_match else ""

    # Detect page type
    page_type = "unknown"
    for pattern, ptype in _PAGE_TYPE_PATTERNS:
        if pattern.search(parsed.path):
            page_type = ptype
            break

    # Build friendly name
    if course_id:
        friendly_name = f"Canvas Course {course_id}"
    elif page_type == "dashboard":
        friendly_name = "Canvas Dashboard"
    else:
        friendly_name = f"Canvas ({domain})"

    return CanvasURLInfo(
        is_canvas=True,
        base_url=base_url,
        domain=domain,
        course_id=course_id,
        page_type=page_type,
        friendly_name=friendly_name,
        api_base=f"{base_url}/api/v1",
    )
