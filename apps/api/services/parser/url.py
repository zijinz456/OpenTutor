"""URL scraping service using trafilatura.

Reference: trafilatura for high-quality web content extraction.
Reuses _markdown_to_tree from pdf.py for tree building.
"""

import uuid
import asyncio
from functools import partial

from models.content import CourseContentTree
from services.parser.pdf import _markdown_to_tree


def _scrape_url(url: str) -> tuple[str, str]:
    """Scrape URL using trafilatura, return (title, markdown_content)."""
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            raise ValueError(f"Failed to fetch URL: {url}")

        # Extract main content as text
        content = trafilatura.extract(
            downloaded,
            include_links=True,
            include_formatting=True,
            include_tables=True,
            output_format="txt",
        )
        if not content:
            raise ValueError(f"No content extracted from URL: {url}")

        # Try to get the title
        metadata = trafilatura.extract_metadata(downloaded)
        title = metadata.title if metadata and metadata.title else url

        return title, content

    except ImportError:
        raise ImportError(
            "trafilatura is required for URL scraping. "
            "Install with: pip install trafilatura"
        )


async def scrape_url_to_tree(
    url: str,
    course_id: uuid.UUID,
) -> list[CourseContentTree]:
    """Scrape URL → extract content → build content tree."""
    loop = asyncio.get_event_loop()

    title, content = await loop.run_in_executor(
        None, partial(_scrape_url, url)
    )

    # Build tree from the extracted content
    nodes = _markdown_to_tree(content, course_id, source_file=title)

    # Update source_type for URL-sourced nodes
    for node in nodes:
        node.source_type = "url"

    return nodes
