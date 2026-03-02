"""Screenpipe integration for screen context awareness.

Optional integration with Screenpipe (https://github.com/mediar-ai/screenpipe)
to sense what the student is currently doing on their screen. Screenpipe
runs locally at localhost:3030 and provides OCR text from recent screen captures.

This is used to enrich the agent's context with information about the student's
current activity (e.g. reading a textbook, looking at slides, watching a lecture).

Enable via SCREENPIPE_ENABLED=true in environment configuration.
Gracefully degrades to None if Screenpipe is not running.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

SCREENPIPE_BASE_URL = "http://localhost:3030"


class ScreenContextService:
    """Query Screenpipe for recent screen context."""

    def __init__(self):
        self._enabled = getattr(settings, "screenpipe_enabled", False)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def get_study_context(self, minutes: int = 15) -> dict | None:
        """Get recent screen context from Screenpipe.

        Args:
            minutes: How far back to look (default 15 minutes).

        Returns:
            Dictionary with extracted study context, or None if unavailable.
            {
                "screen_text": str,  # Concatenated OCR text
                "app_names": list[str],  # Active applications
                "study_topic_hint": str | None,  # LLM-extracted topic hint
            }
        """
        if not self._enabled:
            return None

        try:
            import httpx

            start_time = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{SCREENPIPE_BASE_URL}/search",
                    params={
                        "limit": 20,
                        "content_type": "ocr",
                        "start_time": start_time,
                    },
                )

                if resp.status_code != 200:
                    logger.debug("Screenpipe returned status %d", resp.status_code)
                    return None

                data = resp.json()
                items = data.get("data", [])
                if not items:
                    return None

                # Extract text and app names from results
                screen_texts: list[str] = []
                app_names: set[str] = set()

                for item in items:
                    content = item.get("content", {})
                    text = content.get("text", "").strip()
                    app = content.get("app_name", "")
                    if text:
                        screen_texts.append(text)
                    if app:
                        app_names.add(app)

                if not screen_texts:
                    return None

                combined = "\n".join(screen_texts[:10])  # Limit to avoid token explosion

                # Try to extract a study topic hint
                topic_hint = await self._extract_topic_hint(combined)

                return {
                    "screen_text": combined[:2000],  # Cap at 2k chars
                    "app_names": sorted(app_names),
                    "study_topic_hint": topic_hint,
                }

        except ImportError:
            logger.debug("httpx not available for Screenpipe integration")
            return None
        except Exception as e:
            # Screenpipe not running or connection refused — silent degradation
            logger.debug("Screenpipe unavailable: %s", e)
            return None

    async def _extract_topic_hint(self, screen_text: str) -> str | None:
        """Use LLM to extract the study topic from screen text."""
        if len(screen_text) < 50:
            return None

        try:
            from services.llm.router import get_llm_client

            client = get_llm_client("small")
            response, _ = await client.extract(
                system_prompt=(
                    "You are a study context analyzer. Given OCR text from a student's screen, "
                    "identify what topic they are currently studying. "
                    "Reply with ONLY the topic name (1-5 words), or 'unknown' if unclear."
                ),
                user_message=screen_text[:1000],
            )
            topic = response.strip().strip('"').strip("'")
            return topic if topic.lower() != "unknown" else None
        except Exception:
            return None


# Module-level singleton
_screen_service: ScreenContextService | None = None


def get_screen_context_service() -> ScreenContextService:
    global _screen_service
    if _screen_service is None:
        _screen_service = ScreenContextService()
    return _screen_service
