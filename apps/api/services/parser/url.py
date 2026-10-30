"""HTML text extraction helpers used by the scrape runner and Canvas router."""

import re
import logging

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
