"""Cognitive load NLP analysis -- LLM-based emotion and frustration detection.

Uses the existing local LLM router to classify student messages for:
- frustration, confusion, confidence, engagement level

Also provides text complexity analysis using readability metrics.
"""
import asyncio
import logging
import json
from functools import lru_cache

logger = logging.getLogger(__name__)

# Cache to avoid re-analyzing the same message
_analysis_cache: dict[str, dict] = {}
_cache_lock = asyncio.Lock()
_MAX_CACHE_SIZE = 500


async def analyze_student_affect(message: str) -> dict:
    """Analyze a student message for emotional/cognitive signals.

    Uses the local LLM with a structured prompt to classify:
    - frustration: 0.0-1.0
    - confusion: 0.0-1.0
    - confidence: 0.0-1.0
    - engagement: 0.0-1.0

    Falls back to keyword-based detection if LLM is unavailable.
    """
    # Check cache first
    cache_key = message[:200]  # Truncate for cache key
    async with _cache_lock:
        if cache_key in _analysis_cache:
            return _analysis_cache[cache_key]

    try:
        from services.llm.router import get_llm_client

        client = get_llm_client("fast")

        prompt = (
            "Analyze this student's message for emotional and cognitive state.\n"
            "Rate each dimension from 0.0 to 1.0:\n"
            "- frustration: signs of giving up, annoyance, anger\n"
            "- confusion: not understanding, asking unclear questions\n"
            "- confidence: certainty in their approach\n"
            "- engagement: active participation, curiosity\n\n"
            f'Student message: "{message[:500]}"\n\n'
            'Output JSON only: {"frustration": 0.0, "confusion": 0.0, '
            '"confidence": 0.0, "engagement": 0.0}'
        )

        raw, _ = await client.extract(
            "You are an educational psychology expert. Output valid JSON only.",
            prompt,
        )

        # Parse JSON
        json_start = raw.find("{")
        json_end = raw.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            result = json.loads(raw[json_start:json_end])
            # Clamp values
            for key in ("frustration", "confusion", "confidence", "engagement"):
                result[key] = max(0.0, min(1.0, float(result.get(key, 0.0))))
            result["source"] = "llm"
        else:
            result = _keyword_fallback(message)
    except (json.JSONDecodeError, ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
        logger.warning("LLM affect analysis unavailable, using keyword fallback: %s", exc, exc_info=True)
        result = _keyword_fallback(message)

    # Cache result
    async with _cache_lock:
        if len(_analysis_cache) >= _MAX_CACHE_SIZE:
            # Evict oldest half
            keys = list(_analysis_cache.keys())[: _MAX_CACHE_SIZE // 2]
            for k in keys:
                del _analysis_cache[k]
        _analysis_cache[cache_key] = result

    return result


def _keyword_fallback(message: str) -> dict:
    """Enhanced keyword-based affect detection as fallback."""
    msg_lower = message.lower()

    frustration_keywords = [
        "give up",
        "this is impossible",
        "i can't",
        "i cant",
        "so frustrated",
        "this doesn't make sense",
        "this makes no sense",
        "ugh",
        "argh",
        "why won't",
        "why wont",
        "hate this",
        "this is stupid",
        "ridiculous",
        "waste of time",
        "still wrong",
        "again?!",
        "not working",
    ]
    confusion_keywords = [
        "confused",
        "don't understand",
        "dont understand",
        "what does",
        "what is",
        "how does",
        "i'm lost",
        "im lost",
        "makes no sense",
        "huh?",
        "wait what",
        "can you explain",
        "what do you mean",
        "i don't get",
        "i dont get",
        "unclear",
        "not sure what",
    ]
    confidence_keywords = [
        "i think i understand",
        "got it",
        "makes sense",
        "i see",
        "oh i get it",
        "that's clear",
        "understood",
        "right, so",
        "let me try",
        "i'll try",
        "i know",
        "easy",
    ]
    engagement_keywords = [
        "interesting",
        "cool",
        "tell me more",
        "what about",
        "can we also",
        "i want to know",
        "curious",
        "how about",
        "what if",
        "let me think",
        "actually",
        "wait",
    ]

    def _score(keywords: list[str]) -> float:
        matches = sum(1 for kw in keywords if kw in msg_lower)
        return min(matches / 2.0, 1.0)

    return {
        "frustration": _score(frustration_keywords),
        "confusion": _score(confusion_keywords),
        "confidence": _score(confidence_keywords),
        "engagement": _score(engagement_keywords),
        "source": "keyword",
    }


def compute_text_complexity(text: str) -> dict:
    """Compute readability metrics for tutor response complexity.

    Uses simple readability formulas (no external dependencies).
    Returns complexity score 0.0-1.0 and metrics.
    """
    # Simple readability: average words per sentence + average word length
    sentences = [
        s.strip()
        for s in text.replace("!", ".").replace("?", ".").split(".")
        if s.strip()
    ]
    words = text.split()

    if not sentences or not words:
        return {
            "complexity": 0.0,
            "avg_words_per_sentence": 0,
            "avg_word_length": 0,
        }

    avg_words_per_sentence = len(words) / len(sentences)
    avg_word_length = sum(len(w) for w in words) / len(words)

    # Flesch-Kincaid approximation (simplified)
    # Higher score = more complex
    complexity = min(
        1.0,
        max(
            0.0,
            (avg_words_per_sentence - 10) / 20 * 0.5  # 10-30 words/sentence
            + (avg_word_length - 4) / 4 * 0.5,  # 4-8 chars/word
        ),
    )

    return {
        "complexity": round(complexity, 3),
        "avg_words_per_sentence": round(avg_words_per_sentence, 1),
        "avg_word_length": round(avg_word_length, 1),
        "sentence_count": len(sentences),
        "word_count": len(words),
    }
