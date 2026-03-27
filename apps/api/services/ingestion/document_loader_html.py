"""HTML cleaning and text extraction utilities for document_loader.

Ported from GPT-Researcher scraper/utils.py:
- clean_soup() -- remove unwanted tags
- clean_soup_canvas_aware() -- Canvas LMS aware cleaner
- extract_title() -- extract title from BeautifulSoup
- get_text_from_soup() -- get clean text from BeautifulSoup

Extracted from document_loader.py.
"""

import re
from urllib.parse import urlparse


def _clean_title_text(value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "")).strip()
    return re.sub(r"\s*[|\-–:]\s*(home|index)$", "", value, flags=re.IGNORECASE).strip()


def _humanize_slug_from_url(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    last_segment = parsed.path.rstrip("/").split("/")[-1]
    if not last_segment:
        return parsed.hostname or ""
    slug = re.sub(r"\.[a-z0-9]{1,5}$", "", last_segment, flags=re.IGNORECASE)
    slug = re.sub(r"[-_]+", " ", slug).strip()
    return slug.title() if slug else (parsed.hostname or "")


def _hostname_fallback(url: str | None) -> str:
    if not url:
        return ""
    return urlparse(url).hostname or url


def _normalized_compare_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


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
    # Only remove script, style, and SVG -- preserve everything else
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


def extract_title(soup, url: str | None = None) -> str:
    """Extract title from BeautifulSoup object.

    Ported from GPT-Researcher scraper/utils.py extract_title().
    """
    meta_candidates = [
        soup.find("meta", attrs={"property": "og:title"}),
        soup.find("meta", attrs={"name": "twitter:title"}),
        soup.find("meta", attrs={"property": "twitter:title"}),
    ]
    for tag in meta_candidates:
        if tag and tag.get("content"):
            title = _clean_title_text(tag.get("content", ""))
            if title:
                return title

    if soup.title and soup.title.string:
        title = _clean_title_text(soup.title.string)
        if title:
            return title

    h1 = soup.find("h1")
    if h1:
        title = _clean_title_text(h1.get_text(" ", strip=True))
        if title:
            return title

    slug_title = _humanize_slug_from_url(url)
    if slug_title:
        return slug_title

    return _hostname_fallback(url)


def get_text_from_soup(soup, *, title: str | None = None) -> str:
    """Get clean text from BeautifulSoup object.

    Ported from GPT-Researcher scraper/utils.py get_text_from_soup().
    """
    text_root = soup.body or soup
    text = text_root.get_text(strip=True, separator="\n")
    # Collapse runs of 3+ newlines to double newline (paragraph break)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse runs of spaces (but preserve newlines for structure)
    text = re.sub(r"[^\S\n]{2,}", " ", text)
    text = text.strip()

    if not title or not text:
        return text

    compare_title = _normalized_compare_key(title)
    if not compare_title:
        return text

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    while lines and _normalized_compare_key(lines[0]) == compare_title:
        lines.pop(0)
    if lines and _normalized_compare_key(lines[0]).startswith(compare_title):
        lines.pop(0)

    return "\n".join(lines).strip() or text
