"""URL extraction layers for document_loader.

Contains the multi-layer cascade for URL content extraction:
- Layer 1: Crawl4AI
- Layer 2: httpx + clean_soup
- Layer 3: trafilatura
- Layer 4: Playwright browser cascade

Extracted from document_loader.py.
"""

import asyncio
import logging
import re

import httpx

logger = logging.getLogger(__name__)


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


async def _try_crawl4ai_url(url: str, query: str | None = None) -> tuple[str, str] | None:
    """Layer 1: Crawl4AI -- handles web pages and PDF URLs uniformly.

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
    except (OSError, ConnectionError, TimeoutError, httpx.HTTPError) as e:
        logger.debug(f"Crawl4AI failed for {url}: {e}")
    except (ValueError, RuntimeError) as e:
        logger.exception(f"Unexpected error in Crawl4AI for {url}")
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
        from services.ingestion.document_loader_html import clean_soup, extract_title, get_text_from_soup

        soup = clean_soup(soup)
        title = extract_title(soup, url=url)
        content = get_text_from_soup(soup, title=title)

        if len(content) >= 100:
            return title or url, content
    except ImportError:
        logger.debug("bs4/lxml not installed, skipping httpx+clean_soup layer")
    except (ConnectionError, TimeoutError, httpx.HTTPError) as e:
        logger.debug(f"httpx+clean_soup network error for {url}: {e}")
    except (ValueError, KeyError) as e:
        logger.debug(f"httpx+clean_soup parsing error for {url}: {e}")
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
    except (OSError, ConnectionError, TimeoutError) as e:
        logger.debug(f"trafilatura network error for {url}: {e}")
    except (ValueError, KeyError) as e:
        logger.debug(f"trafilatura parsing error for {url}: {e}")
    return None


async def _try_browser_cascade(url: str) -> tuple[str, str] | None:
    """Layer 4: Playwright browser cascade (existing automation.py)."""
    try:
        from bs4 import BeautifulSoup
        from services.browser.automation import cascade_fetch
        from services.ingestion.document_loader_html import clean_soup, extract_title, get_text_from_soup

        html = await cascade_fetch(url)
        if html:
            soup = BeautifulSoup(html, "lxml")
            soup = clean_soup(soup)
            title = extract_title(soup, url=url)
            text = get_text_from_soup(soup, title=title)
            if text and len(text) >= 50:
                return title or url, text
    except ImportError:
        logger.debug("Browser automation not available, skipping cascade for %s", url)
    except (OSError, ConnectionError, TimeoutError) as e:
        logger.warning("Browser cascade network error for %s: %s", url, e)
    except (RuntimeError, ValueError) as e:
        logger.exception("Browser cascade unexpected error for %s", url)
    return None


async def _extract_from_url(
    url: str,
    query: str | None = None,
    session_name: str | None = None,
) -> tuple[str, str]:
    """URL extraction -- multi-layer cascade with Canvas API priority.

    Fallback cascade:
    0. Canvas REST API (structured data, no HTML scraping needed)
    1. Crawl4AI (best quality -- Markdown + media + metadata + BM25 filtering)
    2. httpx + clean_soup (GPT-Researcher pattern)
    3. trafilatura
    4. Playwright (existing cascade from automation.py)
    """
    from services.ingestion.canvas_loader import _try_canvas_api

    # Layer 0: Canvas REST API (structured data -- bypasses HTML scraping)
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
