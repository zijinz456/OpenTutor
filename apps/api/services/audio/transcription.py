"""Speech-to-Text service using OpenAI Whisper API.

Converts audio bytes to text. Used by the voice WebSocket endpoint.
"""

import io
import logging
from typing import Any

from config import settings

logger = logging.getLogger(__name__)


class TranscriptionService:
    """OpenAI Whisper API wrapper for speech-to-text."""

    def __init__(self):
        self._client: Any = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str | None = None,
        filename: str = "audio.webm",
    ) -> dict:
        """Transcribe audio bytes to text using OpenAI Whisper.

        Args:
            audio_bytes: Raw audio data (supports webm, mp3, wav, m4a, ogg, flac).
            language: Optional ISO-639-1 language code hint (e.g. "en", "zh").
            filename: Virtual filename for content-type detection.

        Returns:
            {"text": str, "language": str | None}
        """
        client = self._get_client()

        # Wrap bytes in a file-like object with a name for MIME detection
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        try:
            response = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                **({"language": language} if language else {}),
            )
            text = response.text.strip()
            logger.info("STT transcribed %d bytes → %d chars", len(audio_bytes), len(text))
            return {"text": text, "language": language}
        except Exception as e:
            logger.error("STT transcription failed: %s", e, exc_info=True)
            raise


# Module-level singleton (lazy-initialized)
_stt_service: TranscriptionService | None = None


def get_stt_service() -> TranscriptionService:
    global _stt_service
    if _stt_service is None:
        _stt_service = TranscriptionService()
    return _stt_service
