"""HTML cleaning and text extraction utilities for document_loader.

Ported from GPT-Researcher scraper/utils.py:
- clean_soup() -- remove unwanted tags
- clean_soup_canvas_aware() -- Canvas LMS aware cleaner
- extract_title() -- extract title from BeautifulSoup
- get_text_from_soup() -- get clean text from BeautifulSoup

Extracted from document_loader.py.
"""

import re


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
