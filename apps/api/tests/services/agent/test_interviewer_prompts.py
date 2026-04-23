"""Unit tests for ``services.agent.agents.interviewer_prompts``.

Covers the grounding loader (file resolution + section extraction + TTL
cache) and the ``_todo_density`` helper that gates generic-question
fallback in the Q generator.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.agent.agents.interviewer_prompts import (
    _GROUNDING_CACHE,
    _load_grounding_excerpt,
    _todo_density,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Each test starts with an empty TTL cache to isolate file-read assertions."""
    _GROUNDING_CACHE.clear()


def test_load_grounding_excerpt_behavioral() -> None:
    """Behavioral mode pulls the ``3ddepo-search`` STAR story by slug."""
    excerpt = _load_grounding_excerpt("3ddepo-search", "behavioral")
    assert excerpt, "behavioral excerpt must be non-empty"
    assert "3ddepo" in excerpt.lower() or "3ddepo-search" in excerpt.lower()


def test_load_grounding_excerpt_technical() -> None:
    """Technical mode pulls the code_defense_drill section mentioning CLIP/FAISS."""
    excerpt = _load_grounding_excerpt("3ddepo-search", "technical")
    assert excerpt, "technical excerpt must be non-empty"
    assert "CLIP" in excerpt or "FAISS" in excerpt


def test_load_grounding_excerpt_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """Second call with the same key must not re-read the file from disk."""
    # Warm the cache using the real loader.
    first = _load_grounding_excerpt("3ddepo-search", "behavioral")
    assert first

    # Now count any further ``Path.read_text`` calls — a cache hit means 0.
    read_calls = {"n": 0}
    original_read_text = Path.read_text

    def counting_read_text(self: Path, *args: object, **kwargs: object) -> str:
        read_calls["n"] += 1
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    second = _load_grounding_excerpt("3ddepo-search", "behavioral")
    assert second == first
    assert read_calls["n"] == 0, (
        f"cached call should skip disk; got {read_calls['n']} read_text calls"
    )


def test_todo_density() -> None:
    """``_todo_density`` returns the fraction of ``_TODO`` tokens in the text."""
    assert _todo_density("_TODO_ _TODO_ foo bar") == pytest.approx(0.5)
    assert _todo_density("all real text here") == pytest.approx(0.0)
    assert _todo_density("") == pytest.approx(1.0)
