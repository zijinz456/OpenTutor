"""Unit tests for ``services.ingestion.coursera_adapter`` (Phase 14 T1).

Covers the five criteria from the plan:

1. Happy path: 3-lecture Week-1 ZIP → 2 paired + 1 vtt-only, sorted.
2. Path traversal rejection: ZIP containing ``../etc/passwd`` is refused.
3. Zip bomb: advertised ``file_size`` above the 2 GiB cap is refused.
4. File-count cap: ZIPs with >500 entries are refused.
5. Multi-language VTT: lexicographically-first VTT wins; warning logged.
"""

from __future__ import annotations

import io
import logging
import zipfile

import pytest

from schemas.coursera import LecturePair
from services.ingestion.coursera_adapter import (
    CourseraAdapterError,
    merge_lecture_markdown,
    parse_coursera_zip,
    vtt_to_text,
)


def _make_zip(entries: list[tuple[str, bytes]]) -> bytes:
    """Build an in-memory ZIP from ``(path, bytes)`` pairs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for path, data in entries:
            zf.writestr(path, data)
    return buf.getvalue()


# ── 1. Happy path ───────────────────────────────────────────────────────────


def test_happy_path_three_lectures_two_paired_one_vtt_only() -> None:
    zip_bytes = _make_zip(
        [
            ("Week-1/L1-Intro.vtt", b"WEBVTT\n\n00:00.000 --> 00:01.000\nhi"),
            ("Week-1/L1-Intro.pdf", b"%PDF-1.4 intro"),
            ("Week-1/L2-Planner.vtt", b"WEBVTT\n\n00:00.000 --> 00:01.000\nplan"),
            ("Week-1/L2-Planner.pdf", b"%PDF-1.4 planner"),
            ("Week-1/L3-Memory.vtt", b"WEBVTT\n\n00:00.000 --> 00:01.000\nmem"),
        ]
    )

    pairs = parse_coursera_zip(zip_bytes)

    assert len(pairs) == 3
    assert [p.lecture_index for p in pairs] == [1, 2, 3]
    assert all(p.week_index == 1 for p in pairs)

    by_idx = {p.lecture_index: p for p in pairs}

    l1 = by_idx[1]
    assert l1.vtt_path == "Week-1/L1-Intro.vtt"
    assert l1.pdf_path == "Week-1/L1-Intro.pdf"
    assert l1.vtt_bytes is not None and l1.vtt_bytes.startswith(b"WEBVTT")
    assert l1.pdf_bytes is not None and l1.pdf_bytes.startswith(b"%PDF")

    l2 = by_idx[2]
    assert l2.vtt_path == "Week-1/L2-Planner.vtt"
    assert l2.pdf_path == "Week-1/L2-Planner.pdf"
    assert l2.vtt_bytes is not None
    assert l2.pdf_bytes is not None

    l3 = by_idx[3]
    assert l3.vtt_path == "Week-1/L3-Memory.vtt"
    assert l3.pdf_path is None
    assert l3.vtt_bytes is not None
    assert l3.pdf_bytes is None


# ── 2. Path traversal ───────────────────────────────────────────────────────


def test_path_traversal_rejected() -> None:
    # zipfile normalizes leading slashes, so use ``..`` segment which survives.
    zip_bytes = _make_zip(
        [
            ("Week-1/L1-Intro.vtt", b"WEBVTT"),
            ("../etc/passwd", b"root:x:0:0"),
        ]
    )

    with pytest.raises(CourseraAdapterError) as exc_info:
        parse_coursera_zip(zip_bytes)

    reason = exc_info.value.reason.lower()
    assert "path traversal" in reason or "invalid path" in reason


# ── 3. Zip bomb (advertised size) ───────────────────────────────────────────


def test_zip_bomb_uncompressed_size_cap_rejected() -> None:
    # Build a real (tiny) ZIP, then monkey-patch the ``ZipInfo.file_size``
    # on read by writing out a crafted header. Simpler: patch via an in-memory
    # override — we feed ``parse_coursera_zip`` a ZIP whose header claims
    # 3 GiB even though the payload is small.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("Week-1/huge.pdf", b"tiny payload")

    # Re-open, mutate the header's advertised ``file_size`` before we hand it
    # back to the adapter. ``ZipFile.infolist`` reads ``file_size`` from the
    # central directory, so we patch by round-tripping through a subclass.
    class _LyingZip(zipfile.ZipFile):
        def infolist(self) -> list[zipfile.ZipInfo]:
            infos = super().infolist()
            for zi in infos:
                zi.file_size = 3 * 1024 * 1024 * 1024  # 3 GiB
            return infos

    # Patch adapter's ``zipfile.ZipFile`` reference to use our lying class.
    import services.ingestion.coursera_adapter as mod

    original = mod.zipfile.ZipFile
    mod.zipfile.ZipFile = _LyingZip  # type: ignore[misc]
    try:
        with pytest.raises(CourseraAdapterError) as exc_info:
            parse_coursera_zip(buf.getvalue())
    finally:
        mod.zipfile.ZipFile = original  # type: ignore[misc]

    reason = exc_info.value.reason.lower()
    assert "size cap" in reason or "too large" in reason


# ── 4. File count cap ───────────────────────────────────────────────────────


def test_file_count_cap_rejected() -> None:
    entries: list[tuple[str, bytes]] = [
        (f"Week-1/file_{i:03d}.txt", b"") for i in range(600)
    ]
    zip_bytes = _make_zip(entries)

    with pytest.raises(CourseraAdapterError) as exc_info:
        parse_coursera_zip(zip_bytes)

    reason = exc_info.value.reason.lower()
    assert "file count" in reason or "count cap" in reason


# ── 5. Multi-language VTT (Flag 5 default = lexicographically first) ────────


def test_multi_language_vtt_picks_lexicographically_first(
    caplog: pytest.LogCaptureFixture,
) -> None:
    zip_bytes = _make_zip(
        [
            ("Week-1/L1-Intro.en.vtt", b"WEBVTT en"),
            ("Week-1/L1-Intro.uk.vtt", b"WEBVTT uk"),
            ("Week-1/L1-Intro.pdf", b"%PDF-1.4 intro"),
        ]
    )

    with caplog.at_level(logging.WARNING, logger="services.ingestion.coursera_adapter"):
        pairs = parse_coursera_zip(zip_bytes)

    assert len(pairs) == 1
    p = pairs[0]
    assert p.vtt_path == "Week-1/L1-Intro.en.vtt"  # .en sorts before .uk
    assert p.vtt_bytes == b"WEBVTT en"
    assert p.pdf_path == "Week-1/L1-Intro.pdf"

    matched = any("multi_vtt_detected" in rec.message for rec in caplog.records)
    assert matched, (
        f"expected multi_vtt_detected; got: {[r.message for r in caplog.records]}"
    )


# ── 6. vtt_to_text — real cue sample ────────────────────────────────────────


def test_vtt_to_text_real_sample_strips_timestamps_and_tags() -> None:
    """Realistic VTT (header + NOTE + speaker/italic tags) reduces to plain lines."""
    vtt = (
        "WEBVTT\n"
        "\n"
        "NOTE This is a block-level comment that must be skipped.\n"
        "\n"
        "1\n"
        "00:00:01.000 --> 00:00:05.000\n"
        "<v Lisa>Welcome to lecture one.</v>\n"
        "\n"
        "2\n"
        "00:00:06.000 --> 00:00:09.000\n"
        "Today we will discuss <i>gradient descent</i>.\n"
    )
    out = vtt_to_text(vtt.encode("utf-8"))

    assert "Welcome to lecture one." in out
    assert "Today we will discuss gradient descent." in out
    assert "-->" not in out
    assert "WEBVTT" not in out
    assert "<v" not in out
    assert "<i" not in out
    assert "NOTE" not in out


# ── 7. vtt_to_text — fallback on malformed ──────────────────────────────────


def test_vtt_to_text_fallback_on_malformed(caplog: pytest.LogCaptureFixture) -> None:
    """Bytes without WEBVTT header make webvtt-py raise; fallback yields text."""
    malformed = (
        b"garbage-first-line\n00:00:01.000 --> 00:00:05.000\nFallback content kept.\n"
    )

    with caplog.at_level(logging.WARNING, logger="services.ingestion.coursera_adapter"):
        out = vtt_to_text(malformed)

    assert out.strip()  # non-empty
    assert "Fallback content kept." in out
    assert "-->" not in out
    matched = any("webvtt_parse_fallback" in rec.message for rec in caplog.records)
    assert matched, (
        f"expected webvtt_parse_fallback warning; "
        f"got: {[r.message for r in caplog.records]}"
    )


# ── 8-10. merge_lecture_markdown ────────────────────────────────────────────


def _patch_pdf_extractor(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    """Stub ``document_loader_formats._extract_pdf_fallback`` to return fixed text."""
    import services.ingestion.document_loader_formats as dlf

    monkeypatch.setattr(
        dlf,
        "_extract_pdf_fallback",
        lambda path: ("lecture", text),
    )


def test_merge_lecture_markdown_full_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both VTT + PDF → both headings present in the merged markdown."""
    _patch_pdf_extractor(monkeypatch, "Slide text here")

    pair = LecturePair(
        week_index=1,
        lecture_index=1,
        title="Intro to Agents",
        vtt_path="Week-1/L1-Intro.vtt",
        pdf_path="Week-1/L1-Intro.pdf",
        vtt_bytes=(b"WEBVTT\n\n00:00:01.000 --> 00:00:05.000\nAgents overview.\n"),
        pdf_bytes=b"%PDF-1.4 fake",
    )

    filename, data = merge_lecture_markdown(pair)

    assert filename.endswith(".coursera.md")
    assert filename == "intro-to-agents.coursera.md"
    markdown = data.decode("utf-8")  # must be valid utf-8
    assert "## Intro to Agents" in markdown
    assert "### Slides" in markdown
    assert "Slide text here" in markdown
    assert "### Transcript" in markdown
    assert "Agents overview." in markdown


def test_merge_lecture_markdown_vtt_only() -> None:
    """pdf_bytes=None → Slides section (and heading) is omitted."""
    pair = LecturePair(
        week_index=1,
        lecture_index=2,
        title="Planner Loop",
        vtt_path="Week-1/L2-Planner.vtt",
        pdf_path=None,
        vtt_bytes=(b"WEBVTT\n\n00:00:01.000 --> 00:00:05.000\nPlan then act.\n"),
        pdf_bytes=None,
    )

    filename, data = merge_lecture_markdown(pair)

    assert filename == "planner-loop.coursera.md"
    markdown = data.decode("utf-8")
    assert "## Planner Loop" in markdown
    assert "### Transcript" in markdown
    assert "Plan then act." in markdown
    assert "### Slides" not in markdown


def test_merge_lecture_markdown_pdf_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """vtt_bytes=None → Transcript section (and heading) is omitted."""
    _patch_pdf_extractor(monkeypatch, "Memory module diagram")

    pair = LecturePair(
        week_index=1,
        lecture_index=3,
        title="Memory Module",
        vtt_path=None,
        pdf_path="Week-1/L3-Memory.pdf",
        vtt_bytes=None,
        pdf_bytes=b"%PDF-1.4 fake",
    )

    filename, data = merge_lecture_markdown(pair)

    assert filename == "memory-module.coursera.md"
    markdown = data.decode("utf-8")
    assert "## Memory Module" in markdown
    assert "### Slides" in markdown
    assert "Memory module diagram" in markdown
    assert "### Transcript" not in markdown
