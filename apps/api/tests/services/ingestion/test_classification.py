"""Unit tests for ``services.ingestion.classification`` (Phase 14 T4).

Only the filename-regex layer is covered here — content heuristics and the
LLM fallback have their own tests elsewhere. The purpose is to lock in the
Coursera adapter contract: synthetic ``*.coursera.md`` files produced by
``coursera_adapter.merge_lecture_markdown`` classify as ``lecture_slides``
via the cheap ``filename_regex`` path, ahead of the generic ``.md → notes``
text fallback in ``classify_document``.
"""

from __future__ import annotations

import pytest

from services.ingestion.classification import (
    classify_by_filename,
    classify_document,
)


def test_classify_by_filename_coursera_md_is_lecture_slides() -> None:
    """``*.coursera.md`` → ``lecture_slides`` via filename regex.

    This is the synthetic filename the Coursera adapter emits when pairing a
    VTT transcript with its PDF slides, so it MUST be routed to the
    lecture-slides pipeline at step 0 (zero LLM cost).
    """
    assert classify_by_filename("L1-Intro.coursera.md") == "lecture_slides"


@pytest.mark.asyncio
async def test_classify_document_coursera_md_reports_filename_regex() -> None:
    """Full ``classify_document`` also reports the ``filename_regex`` method."""
    category, method = await classify_document(
        content="",
        filename="L1-Intro.coursera.md",
    )
    assert category == "lecture_slides"
    assert method == "filename_regex"


def test_classify_by_filename_plain_md_stays_notes() -> None:
    """A plain ``.md`` file must NOT be matched as ``lecture_slides``.

    The Coursera pattern is deliberately scoped to the double-suffix
    ``.coursera.md`` so generic markdown uploads keep their existing routing
    (either ``notes`` via the word-level regex, or the ``.md`` text fallback
    inside ``classify_document``).
    """
    assert classify_by_filename("random-notes.md") != "lecture_slides"


def test_classify_by_filename_coursera_before_generic_notes() -> None:
    """A filename that matches both patterns still resolves to lecture_slides.

    ``study-notes.coursera.md`` would match the generic ``notes?`` pattern if
    iteration hit it first. The Coursera pattern is registered ahead of the
    notes pattern on purpose — this test pins that ordering so a future dict
    reshuffle cannot silently regress Coursera imports to ``notes``.
    """
    assert classify_by_filename("study-notes.coursera.md") == "lecture_slides"
