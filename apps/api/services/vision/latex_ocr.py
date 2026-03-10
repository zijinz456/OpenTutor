"""LaTeX-OCR service using pix2tex.

Extracts mathematical formulas from images and converts them to LaTeX strings.
Used to enhance image-based math tutoring by providing the LLM with both
the original image and extracted LaTeX for more accurate responses.

Requires: pip install pix2tex
"""

import base64
import binascii
import io
import logging
from typing import Any

logger = logging.getLogger(__name__)


class LaTeXOCRService:
    """pix2tex-based math formula recognition."""

    def __init__(self):
        self._model: Any = None
        self._available: bool | None = None

    def _ensure_model(self) -> bool:
        """Lazily load the pix2tex model. Returns True if available."""
        if self._available is not None:
            return self._available

        try:
            from pix2tex.cli import LatexOCR
            self._model = LatexOCR()
            self._available = True
            logger.info("LaTeX-OCR model loaded successfully")
        except ImportError:
            self._available = False
            logger.info("pix2tex not installed — LaTeX-OCR disabled")
        except (OSError, RuntimeError, ValueError) as e:
            self._available = False
            logger.exception("Failed to load LaTeX-OCR model")

        return self._available

    @property
    def is_available(self) -> bool:
        return self._ensure_model()

    def extract_latex(self, image_bytes: bytes) -> str | None:
        """Extract LaTeX from an image.

        Args:
            image_bytes: Raw image data (PNG, JPEG, etc.)

        Returns:
            LaTeX string (e.g. "\\frac{1}{2}") or None if extraction fails.
        """
        if not self._ensure_model():
            return None

        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes))
            latex = self._model(img)
            if latex and latex.strip():
                logger.info("LaTeX-OCR extracted: %s", latex[:100])
                return latex.strip()
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("LaTeX-OCR extraction failed: %s", e)

        return None

    def extract_latex_from_base64(self, data: str, media_type: str = "image/png") -> str | None:
        """Extract LaTeX from a base64-encoded image."""
        try:
            image_bytes = base64.b64decode(data)
            return self.extract_latex(image_bytes)
        except (ValueError, binascii.Error) as e:
            logger.warning("Failed to decode base64 for LaTeX-OCR: %s", e)
            return None


# Module-level singleton
_latex_ocr: LaTeXOCRService | None = None


def get_latex_ocr_service() -> LaTeXOCRService:
    global _latex_ocr
    if _latex_ocr is None:
        _latex_ocr = LaTeXOCRService()
    return _latex_ocr


def try_extract_latex(images: list[dict]) -> list[str]:
    """Best-effort LaTeX extraction from a list of image attachments.

    Returns list of LaTeX strings for images that contain math formulas.
    Silently returns [] if pix2tex is not installed or no math is found.
    """
    service = get_latex_ocr_service()
    if not service.is_available:
        return []

    results = []
    for img in images:
        data = img.get("data", "")
        if not data:
            continue
        latex = service.extract_latex_from_base64(data, img.get("media_type", "image/png"))
        if latex:
            results.append(latex)

    return results
