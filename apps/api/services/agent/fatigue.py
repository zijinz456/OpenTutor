"""Fatigue detection — OpenAkita Persona pattern.

Detects student frustration/fatigue level from message text using
pre-compiled regex patterns for negative and positive signals.
"""

import re

# Pre-compiled regex patterns for fatigue/positive signals (avoid re-compiling per call).
_FATIGUE_SIGNALS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"(don'?t\s+want\s+to\s+study|give\s+up|so\s+annoying|so\s+tired|can'?t\s+keep\s+going|hate\s+this)", re.IGNORECASE), 0.35),
    (re.compile(r"(can'?t\s+do\s+it|too\s+hard|frustrated|confused)", re.IGNORECASE), 0.3),
    (re.compile(r"(can'?t\s+understand|can'?t\s+learn|why\s+still\s+wrong|wrong\s+again|can'?t\s+figure\s+out)", re.IGNORECASE), 0.3),
    (re.compile(r"(again\s+wrong|still\s+don'?t\s+get|keep\s+getting\s+wrong|makes\s+no\s+sense)", re.IGNORECASE), 0.25),
    (re.compile(r"(forget\s+it|sigh|ugh|whatever|nvm|never\s+mind)", re.IGNORECASE), 0.25),
    (re.compile(r"[😫😤😩😭💀🤯😡]"), 0.2),
]
_POSITIVE_SIGNALS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"(i\s+get\s+it|i\s+understand|so\s+that'?s\s+how|learned\s+it|mastered\s+it|got\s+it\s+done)", re.IGNORECASE), -0.3),
    (re.compile(r"(i see|got it|makes sense|understand now|figured it out)", re.IGNORECASE), -0.3),
    (re.compile(r"(thanks?|not\s+bad|pretty\s+good|great|nice|cool)", re.IGNORECASE), -0.15),
]


def detect_fatigue(message: str) -> float:
    """Detect student frustration/fatigue level (0.0-1.0).

    OpenAkita persona dimension pattern: check signals across multiple categories.
    Positive signals reduce the score to prevent false positives.
    """
    score = 0.0
    for pattern, weight in _FATIGUE_SIGNALS:
        if pattern.search(message):
            score += weight
    for pattern, weight in _POSITIVE_SIGNALS:
        if pattern.search(message):
            score += weight
    return max(0.0, min(score, 1.0))
