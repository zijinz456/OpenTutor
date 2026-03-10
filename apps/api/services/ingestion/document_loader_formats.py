"""Local file format extraction for document_loader.

Contains:
- Local PDF/HTML extraction via Crawl4AI (with fallbacks)
- Office format extraction via GPT-Researcher loader_dict
- Plain text extraction
- Marker model loading

Extracted from document_loader.py.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Office formats handled by loader_dict (GPT-Researcher pattern)
OFFICE_EXTENSIONS = {"doc", "docx", "pptx", "csv", "xls", "xlsx"}

# Text formats read directly
TEXT_EXTENSIONS = {"txt", "md", "rst"}

_marker_models: dict | None = None


async def _extract_local_with_crawl4ai(file_path: str) -> tuple[str, str]:
    """Extract content from local PDF/HTML via Crawl4AI file:// protocol.

    Falls back to legacy extractors if Crawl4AI is unavailable.
    """
    import asyncio

    abs_path = str(Path(file_path).resolve())
    file_url = f"file://{abs_path}"

    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=file_url, config=CrawlerRunConfig())
            if result.success:
                md = result.markdown
                raw = md.raw_markdown if hasattr(md, "raw_markdown") else str(md)
                if raw:
                    title = ""
                    if result.metadata and isinstance(result.metadata, dict):
                        title = result.metadata.get("title", "") or ""
                    return title or Path(file_path).stem, raw
    except ImportError:
        logger.debug("crawl4ai not installed, falling back to legacy extractors")
    except (IOError, OSError) as e:
        logger.debug(f"Crawl4AI local file I/O error for {file_path}: {e}")
    except (ValueError, RuntimeError) as e:
        logger.exception(f"Unexpected error in Crawl4AI local extraction for {file_path}")

    # Fallback for PDF
    ext = Path(file_path).suffix.lstrip(".").lower()
    if ext == "pdf":
        return await asyncio.to_thread(_extract_pdf_fallback, file_path)

    # Fallback for HTML
    if ext in ("html", "htm"):
        return await asyncio.to_thread(_extract_html_fallback, file_path)

    return Path(file_path).stem, ""


def _extract_pdf_fallback(file_path: str) -> tuple[str, str]:
    """PDF fallback: Marker -> pypdf."""
    # Try Marker
    try:
        from marker.converters.pdf import PdfConverter

        converter = PdfConverter(artifact_dict=_get_marker_models())
        rendered = converter(file_path)
        return Path(file_path).stem, rendered.markdown
    except ImportError:
        pass
    except (IOError, OSError) as e:
        logger.warning("Marker PDF file I/O error: %s", e)
    except (ValueError, RuntimeError) as e:
        logger.warning("Marker PDF parsing error: %s", e)

    # Try pypdf
    try:
        import pypdf

        reader = pypdf.PdfReader(file_path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return Path(file_path).stem, text
    except ImportError:
        logger.debug("pypdf not installed, skipping PDF fallback")
    except (IOError, OSError) as e:
        logger.warning("pypdf file I/O error: %s", e)
    except (ValueError, KeyError) as e:
        logger.warning("pypdf parsing error: %s", e)

    return Path(file_path).stem, ""


def _extract_html_fallback(file_path: str) -> tuple[str, str]:
    """HTML fallback: trafilatura -> raw read."""
    try:
        import trafilatura

        with open(file_path) as f:
            html = f.read()
        content = trafilatura.extract(html, include_tables=True) or ""
        if content:
            return Path(file_path).stem, content
    except ImportError:
        logger.debug("trafilatura not installed for HTML extraction of %s", file_path)
    except (IOError, OSError) as e:
        logger.debug("trafilatura HTML file I/O error for %s: %s", file_path, e)
    except (ValueError, KeyError) as e:
        logger.debug("trafilatura HTML parsing error for %s: %s", file_path, e)

    # Raw text fallback
    try:
        return Path(file_path).stem, Path(file_path).read_text(errors="ignore")
    except (IOError, OSError) as e:
        logger.exception("Failed to read file %s", file_path)
        return Path(file_path).stem, ""


def _extract_with_loader_dict(file_path: str, ext: str) -> tuple[str, str]:
    """DOCX/PPTX/XLSX/CSV extraction using GPT-Researcher's loader_dict pattern.

    Reference: gpt_researcher/document/document.py L66-78
    """
    try:
        from langchain_community.document_loaders import (
            UnstructuredCSVLoader,
            UnstructuredExcelLoader,
            UnstructuredPowerPointLoader,
            UnstructuredWordDocumentLoader,
        )

        loader_map = {
            "doc": lambda fp: UnstructuredWordDocumentLoader(fp),
            "docx": lambda fp: UnstructuredWordDocumentLoader(fp),
            "pptx": lambda fp: UnstructuredPowerPointLoader(fp),
            "csv": lambda fp: UnstructuredCSVLoader(fp, mode="elements"),
            "xls": lambda fp: UnstructuredExcelLoader(fp, mode="elements"),
            "xlsx": lambda fp: UnstructuredExcelLoader(fp, mode="elements"),
        }

        factory = loader_map.get(ext)
        if not factory:
            return Path(file_path).stem, ""

        loader = factory(file_path)
        docs = loader.load()
        content = "\n\n".join(doc.page_content for doc in docs if doc.page_content)
        return Path(file_path).stem, content

    except ImportError:
        logger.warning(
            "langchain-community/unstructured not installed. "
            "Falling back to basic extraction for %s files. "
            "Install with: pip install langchain-community unstructured",
            ext,
        )
        return _extract_office_fallback(file_path, ext)
    except (OSError, ValueError, RuntimeError) as e:
        logger.warning("loader_dict extraction failed for %s: %s", file_path, e)
        return _extract_office_fallback(file_path, ext)


def _extract_office_fallback(file_path: str, ext: str) -> tuple[str, str]:
    """Basic fallback for Office formats when Unstructured is unavailable."""
    if ext in ("doc", "docx"):
        try:
            from docx import Document

            doc = Document(file_path)
            content = "\n\n".join(p.text for p in doc.paragraphs if p.text)
            return Path(file_path).stem, content
        except ImportError:
            logger.debug("python-docx not installed for DOCX fallback of %s", file_path)
        except (OSError, ValueError, KeyError) as e:
            logger.exception("DOCX fallback extraction failed for %s", file_path)

    if ext in ("pptx",):
        try:
            from pptx import Presentation

            prs = Presentation(file_path)
            texts = []
            for slide_num, slide in enumerate(prs.slides, 1):
                texts.append(f"## Slide {slide_num}")
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        texts.append(shape.text_frame.text)
            return Path(file_path).stem, "\n\n".join(texts)
        except ImportError:
            logger.debug("python-pptx not installed for PPTX fallback of %s", file_path)
        except (OSError, ValueError, KeyError) as e:
            logger.exception("PPTX fallback extraction failed for %s", file_path)

    return Path(file_path).stem, ""


def _extract_plain_text(file_path: str) -> tuple[str, str]:
    """Direct text read for .txt, .md, .rst, and unknown files."""
    try:
        content = Path(file_path).read_text(errors="ignore")
        return Path(file_path).stem, content
    except OSError as e:
        logger.exception("Failed to read plain text file %s", file_path)
        return Path(file_path).stem, ""


def _get_marker_models() -> dict:
    """Lazy-load Marker models once for local PDF fallback path."""
    global _marker_models
    if _marker_models is None:
        from marker.models import create_model_dict

        _marker_models = create_model_dict()
    return _marker_models
