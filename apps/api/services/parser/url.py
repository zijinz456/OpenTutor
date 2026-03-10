"""URL scraping service — thin wrapper around unified document_loader.

Uses Crawl4AI as primary engine with multi-layer fallback cascade.
Reuses _markdown_to_tree from pdf.py for tree building.
"""

import re
import uuid
import logging

import httpx

from models.content import CourseContentTree
from services.parser.pdf import _markdown_to_tree

logger = logging.getLogger(__name__)


def extract_text_from_html(html: str) -> str:
    """Extract readable text from raw HTML.

    Used by scrape runner and document_loader fallback layers.
    """
    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            include_links=False,
            include_formatting=False,
            include_tables=True,
            output_format="txt",
        )
        return text or ""
    except (ImportError, TypeError, ValueError):
        # Best-effort regex fallback
        clean = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
        clean = re.sub(r"<style[\s\S]*?</style>", " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"<[^>]+>", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean


async def scrape_url_to_tree(
    url: str,
    course_id: uuid.UUID,
) -> list[CourseContentTree]:
    """Scrape URL → extract content → build content tree.

    Delegates to document_loader.extract_content() which uses
    Crawl4AI → httpx+clean_soup → trafilatura → Playwright cascade.
    """
    from services.ingestion.document_loader import extract_content

    try:
        title, content = await extract_content(url=url)
    except (httpx.HTTPError, ConnectionError, TimeoutError, ValueError, RuntimeError, OSError, IOError) as exc:
        logger.exception("URL extraction failed for %s", url)
        return []

    if not content:
        return []

    # Build tree from the extracted content
    nodes = _markdown_to_tree(content, course_id, source_file=title or url)

    # Update source_type for URL-sourced nodes
    for node in nodes:
        node.source_type = "url"

    return nodes
