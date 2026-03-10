"""Shared text utilities for processing LLM responses."""

import json
from typing import Any


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


def parse_llm_json(text: str, *, default: Any = None) -> Any:
    """Parse JSON from LLM output, handling code fences and surrounding text.

    Tries in order:
    1. Strip code fences and parse directly
    2. Find outermost JSON array ([...])
    3. Find outermost JSON object ({...})

    Returns the parsed value, or *default* if nothing could be parsed.
    """
    cleaned = strip_code_fences(text)

    # 1. Direct parse
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Try to find a JSON array
    arr_start = text.find("[")
    arr_end = text.rfind("]") + 1
    if arr_start >= 0 and arr_end > arr_start:
        try:
            return json.loads(text[arr_start:arr_end])
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. Try to find a JSON object
    obj_start = text.find("{")
    obj_end = text.rfind("}") + 1
    if obj_start >= 0 and obj_end > obj_start:
        try:
            return json.loads(text[obj_start:obj_end])
        except (json.JSONDecodeError, ValueError):
            pass

    return default
