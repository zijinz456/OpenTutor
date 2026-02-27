"""Token-aware content trimming — ported from Deep-Research trimPrompt pattern.

Provides smart text truncation that respects semantic boundaries
(paragraphs > sentences > words) instead of naive character slicing.

References:
- Deep-Research: trimPrompt() (ai/providers.ts L65-98)
- Deep-Research: RecursiveCharacterTextSplitter (ai/text-splitter.ts L87-143)
- GPT-Researcher: ContextCompressor (context/compression.py L84-158)
"""

import logging

logger = logging.getLogger(__name__)

# Deep-Research constants
MIN_CHUNK_SIZE = 140   # Safety lower bound (chars)
CHARS_PER_TOKEN = 3    # Rough chars-per-token estimate for overflow calculation

# Separator priority (Deep-Research pattern: paragraph > sentence > word > char)
SEPARATORS = ["\n\n", "\n", ". ", ", ", " "]


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken. Falls back to word-count estimate."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return max(1, int(len(text.split()) * 0.75))


def _recursive_split(text: str, max_chars: int, separators: list[str] | None = None) -> list[str]:
    """Recursively split text by separator priority, respecting semantic boundaries.

    Ported from Deep-Research RecursiveCharacterTextSplitter.
    Separator priority: \\n\\n > \\n > ". " > ", " > " "
    """
    if separators is None:
        separators = SEPARATORS

    if len(text) <= max_chars:
        return [text]

    # Try each separator in priority order
    for sep in separators:
        if sep not in text:
            continue

        parts = text.split(sep)
        chunks = []
        current = ""

        for part in parts:
            candidate = current + sep + part if current else part
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = part

        if current:
            chunks.append(current)

        if chunks:
            return chunks

    # Final fallback: hard character split
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def trim_for_llm(text: str, max_tokens: int = 2000) -> str:
    """Smart text trimming to fit within token budget, preserving semantic boundaries.

    Algorithm (Deep-Research trimPrompt pattern):
    1. Count tokens precisely with tiktoken
    2. If within budget, return as-is
    3. Estimate target character count from overflow
    4. Split by semantic boundaries (paragraph > sentence > word)
    5. Return first chunk that fits
    6. Hard truncate as last resort
    """
    if not text:
        return text

    token_count = _count_tokens(text)
    if token_count <= max_tokens:
        return text

    # Estimate target character count
    overflow_tokens = token_count - max_tokens
    target_chars = max(len(text) - overflow_tokens * CHARS_PER_TOKEN, MIN_CHUNK_SIZE)

    # Split by semantic boundaries
    chunks = _recursive_split(text, int(target_chars))
    if not chunks:
        return text[:int(target_chars)]

    # Take first chunk; verify it fits
    result = chunks[0]
    result_tokens = _count_tokens(result)

    # If still over budget, recursively trim (Deep-Research retry pattern)
    if result_tokens > max_tokens:
        return trim_for_llm(result, max_tokens)

    return result
