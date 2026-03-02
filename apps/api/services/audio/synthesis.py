"""Text-to-Speech service using OpenAI TTS API.

Converts text to audio bytes. Used by the voice WebSocket endpoint
and podcast generation.
"""

import logging
from typing import Any, AsyncIterator, Literal

from config import settings

logger = logging.getLogger(__name__)

Voice = Literal["alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"]

# Sentence-ending punctuation for chunking TTS input
_SENTENCE_ENDS = {".", "!", "?", "\n"}


class SynthesisService:
    """OpenAI TTS API wrapper for text-to-speech."""

    def __init__(self):
        self._client: Any = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

    async def synthesize(
        self,
        text: str,
        voice: Voice = "alloy",
        speed: float = 1.0,
    ) -> bytes:
        """Synthesize text to MP3 audio bytes.

        Args:
            text: Text to convert to speech.
            voice: Voice identifier.
            speed: Playback speed (0.25 to 4.0).

        Returns:
            MP3 audio bytes.
        """
        client = self._get_client()
        response = await client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            speed=speed,
            response_format="mp3",
        )
        audio_bytes = response.content
        logger.info("TTS synthesized %d chars → %d bytes (voice=%s)", len(text), len(audio_bytes), voice)
        return audio_bytes

    async def synthesize_streaming(
        self,
        text: str,
        voice: Voice = "alloy",
        speed: float = 1.0,
    ) -> AsyncIterator[bytes]:
        """Stream TTS audio in chunks using OpenAI streaming response.

        Yields MP3 audio chunks as they become available.
        """
        client = self._get_client()
        async with client.audio.speech.with_streaming_response.create(
            model="tts-1",
            voice=voice,
            input=text,
            speed=speed,
            response_format="mp3",
        ) as response:
            async for chunk in response.iter_bytes(chunk_size=4096):
                yield chunk

    async def synthesize_sentences(
        self,
        text_stream: AsyncIterator[str],
        voice: Voice = "alloy",
        speed: float = 1.0,
    ) -> AsyncIterator[bytes]:
        """Buffer streaming text into sentences, then TTS each sentence.

        This provides low-latency sentence-level audio streaming:
        accumulate text until a sentence boundary, synthesize that sentence,
        and yield the audio immediately.
        """
        buffer = ""
        async for token in text_stream:
            buffer += token
            # Check if buffer ends with sentence-ending punctuation
            stripped = buffer.rstrip()
            if stripped and stripped[-1] in _SENTENCE_ENDS and len(stripped) > 20:
                audio = await self.synthesize(buffer.strip(), voice=voice, speed=speed)
                yield audio
                buffer = ""

        # Flush remaining buffer
        if buffer.strip():
            audio = await self.synthesize(buffer.strip(), voice=voice, speed=speed)
            yield audio


# Module-level singleton
_tts_service: SynthesisService | None = None


def get_tts_service() -> SynthesisService:
    global _tts_service
    if _tts_service is None:
        _tts_service = SynthesisService()
    return _tts_service
