"""Unified content extraction -- Crawl4AI as primary engine + GPT-Researcher loader_dict for Office formats.

Architecture:
- Crawl4AI: web pages (HTTP/HTTPS), PDF (URL + local via file://), local HTML
- loader_dict: DOCX, PPTX, XLSX, CSV, TXT, MD (Office/text formats Crawl4AI doesn't support)
- Fallback layers: httpx + clean_soup, trafilatura, Playwright cascade

Features:
- BM25 content filtering for focused extraction from noisy web pages
- Batch URL crawling via arun_many() for bulk ingestion
- Media/links metadata extraction and storage

Split into sub-modules:
- document_loader_extractors: URL extraction layers (Crawl4AI, httpx, trafilatura, Playwright)
- document_loader_formats: Local file/office/PDF/HTML extraction
- document_loader_html: HTML cleaning utilities
"""

import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass, field

import httpx

from services.ingestion.document_loader_extractors import (  # noqa: F401
    _build_crawl4ai_config,
    _extract_from_url,
    _try_crawl4ai_url,
    _try_httpx_clean_soup,
    _try_trafilatura_url,
    _try_browser_cascade,
)
from services.ingestion.document_loader_formats import (  # noqa: F401
    OFFICE_EXTENSIONS,
    TEXT_EXTENSIONS,
    _extract_local_with_crawl4ai,
    _extract_pdf_fallback,
    _extract_html_fallback,
    _extract_with_loader_dict,
    _extract_office_fallback,
    _extract_plain_text,
    _get_marker_models,
)
from services.ingestion.document_loader_html import (  # noqa: F401
    clean_soup,
    clean_soup_canvas_aware,
    extract_title,
    get_text_from_soup,
)

logger = logging.getLogger(__name__)


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
        session_name: Optional Playwright session name for authenticated Canvas API access.
    """
    if url:
        return await _extract_from_url(url, query=query, session_name=session_name)

    if not file_path:
        return "", ""

    ext = Path(file_path).suffix.lstrip(".").lower()

    # PDF and HTML -> Crawl4AI via file:// protocol
    if ext == "pdf":
        return await _extract_local_with_crawl4ai(file_path)
    if ext in ("html", "htm"):
        return await _extract_local_with_crawl4ai(file_path)

    # Office formats -> GPT-Researcher loader_dict
    if ext in OFFICE_EXTENSIONS:
        return await asyncio.to_thread(_extract_with_loader_dict, file_path, ext)

    # Text formats -> direct read
    if ext in TEXT_EXTENSIONS:
        return await asyncio.to_thread(_extract_plain_text, file_path)

    # Unknown -> try text read
    return await asyncio.to_thread(_extract_plain_text, file_path)


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
    except (OSError, ConnectionError, TimeoutError, httpx.HTTPError) as e:
        logger.debug(f"Crawl4AI rich extraction failed for {url}: {e}")
    except (ValueError, RuntimeError) as e:
        logger.exception(f"Unexpected error in Crawl4AI rich extraction for {url}")

    # Fallback to basic extraction
    title, content = await _extract_from_url(url, query=query)
    return ExtractionResult(title=title, content=content)


async def extract_content_batch(
    urls: list[str],
    query: str | None = None,
) -> list[ExtractionResult]:
    """Batch URL extraction using Crawl4AI arun_many() for parallel crawling.

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
    except (OSError, ConnectionError, TimeoutError, httpx.HTTPError) as e:
        logger.debug(f"Crawl4AI batch extraction failed: {e}")
    except (ValueError, RuntimeError) as e:
        logger.exception(f"Unexpected error in Crawl4AI batch extraction")

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

    # Images -- Crawl4AI provides scored image data
    images = []
    if hasattr(result, "media") and isinstance(result.media, dict):
        for img in result.media.get("images", []):
            images.append({
                "src": img.get("src", ""),
                "alt": img.get("alt", ""),
                "score": img.get("score", 0),
                "description": img.get("desc", ""),
            })

    # Links -- internal and external
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


# Backward-compatible re-exports from canvas_loader
from services.ingestion.canvas_loader import (  # noqa: E402, F401
    _load_session_cookies,
    CanvasAuthExpiredError,
    CanvasExtraction,
    _extract_file_urls_from_html,
    _canvas_api_paginate,
    _try_canvas_api,
    _try_canvas_api_deep,
    download_canvas_file,
    _parse_canvas_quiz_question,
)
