"""Voice services — speech-to-text via OpenAI Whisper.

Phase 8 (voice_whisper_phase8.md) T1. Module is intentionally isolated
from the LLM provider abstraction: Whisper is a distinct API surface
(``/audio/transcriptions`` vs ``/chat/completions``) and the other
providers registered in ``services.llm`` (Anthropic, Ollama, mocks) do
not speak it. Keeping the client here means ``LLMClient`` stays focused
on chat and we avoid widening its abstract surface for a one-off
capability.

Audio bytes are never persisted. See ``whisper_client.transcribe_audio``.
"""

from services.voice.whisper_client import WhisperError, transcribe_audio

__all__ = ["WhisperError", "transcribe_audio"]
