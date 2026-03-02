"""Shared text utilities for processing LLM responses."""


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM output.

    Handles patterns like:
        ```json
        {"key": "value"}
        ```
    Returns the inner content with leading/trailing whitespace stripped.
    """
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence line (e.g. ```json)
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        # Remove closing fence
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text
