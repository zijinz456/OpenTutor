"""Coursera ZIP ingest adapter (Phase 14 T1).

Parses a user-supplied ZIP of locally-downloaded Coursera lecture assets
(VTT transcripts + PDF slides) into an ordered list of ``LecturePair``
objects. Pairing is loose: a lecture may ship with only a transcript or
only slides, but never neither.

The adapter runs entirely in-memory (``io.BytesIO``) and enforces zip-bomb
and path-traversal guards before extracting any bytes.
"""

from __future__ import annotations

import io
import logging
import re
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

from schemas.coursera import LecturePair

logger = logging.getLogger(__name__)

# ── Security caps ──
_MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB total
_MAX_SINGLE_FILE_BYTES = 100 * 1024 * 1024  # 100 MiB per file
_MAX_FILE_COUNT = 500
_SYMLINK_UNIX_MODE = 0o120000
_UNIX_FILE_TYPE_MASK = 0o170000

# ── Normalization ──
_STEM_SUFFIXES = (
    "_transcript",
    "-transcript",
    " - slides",
    " (slides)",
    ".en",
    ".uk",
    ".ru",
)
_WEEK_RE = re.compile(r"(?i)^week[-_\s]*(\d+)$")
_LECTURE_RE = re.compile(r"(?i)(?:l|lecture)[-_\s]*(\d+)")
_WINDOWS_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")


class CourseraAdapterError(Exception):
    """Raised when a Coursera ZIP fails validation (security or structure)."""

    def __init__(self, reason: str, hint: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.hint = hint


def parse_coursera_zip(zip_bytes: bytes) -> list[LecturePair]:
    """Parse a Coursera ZIP into an ordered list of ``LecturePair`` objects."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        infos = zf.infolist()
        _enforce_security_caps(infos)
        pairs = _collect_pairs(zf, infos)

    if not pairs:
        raise CourseraAdapterError(
            reason="no lectures found",
            hint="ZIP must contain at least one .vtt or .pdf file.",
        )
    pairs.sort(key=lambda p: (p.week_index, p.lecture_index))
    return pairs


# ── Security ──


def _enforce_security_caps(infos: list[zipfile.ZipInfo]) -> None:
    """Reject the ZIP up-front if any guard (count / size / path / symlink) trips."""
    if len(infos) > _MAX_FILE_COUNT:
        raise CourseraAdapterError(
            reason=f"file count cap exceeded: {len(infos)} > {_MAX_FILE_COUNT}",
            hint="Split the course into smaller uploads.",
        )

    total = 0
    for zinfo in infos:
        _reject_bad_path(zinfo.filename)
        _reject_symlink(zinfo)
        if zinfo.file_size > _MAX_SINGLE_FILE_BYTES:
            raise CourseraAdapterError(
                reason=(
                    f"single-file size cap exceeded: {zinfo.filename} "
                    f"({zinfo.file_size} > {_MAX_SINGLE_FILE_BYTES} bytes)"
                ),
                hint="Remove oversized files; Coursera assets rarely exceed 100 MiB.",
            )
        total += zinfo.file_size
        if total > _MAX_UNCOMPRESSED_BYTES:
            raise CourseraAdapterError(
                reason=(
                    f"uncompressed size cap exceeded: advertised total "
                    f"{total} > {_MAX_UNCOMPRESSED_BYTES} bytes (zip bomb?)"
                ),
                hint="Upload a smaller subset.",
            )


def _reject_bad_path(name: str) -> None:
    """Reject absolute paths, drive-letter roots, and ``..`` traversal segments."""
    if not name:
        return
    if name.startswith("/") or name.startswith("\\"):
        raise CourseraAdapterError(
            reason=f"invalid path (absolute): {name!r}",
            hint="Re-zip with relative paths only.",
        )
    if _WINDOWS_ABS_RE.match(name):
        raise CourseraAdapterError(
            reason=f"invalid path (windows absolute): {name!r}",
            hint="Re-zip with relative paths only.",
        )
    parts = name.replace("\\", "/").split("/")
    if any(p == ".." for p in parts):
        raise CourseraAdapterError(
            reason=f"path traversal detected: {name!r}",
            hint="Re-zip without '..' segments.",
        )


def _reject_symlink(zinfo: zipfile.ZipInfo) -> None:
    """Reject Unix symlink entries encoded in ``external_attr``."""
    mode = (zinfo.external_attr >> 16) & _UNIX_FILE_TYPE_MASK
    if mode == _SYMLINK_UNIX_MODE:
        raise CourseraAdapterError(
            reason=f"symlink entry rejected: {zinfo.filename!r}",
            hint="Re-zip without symlinks.",
        )


# ── Pairing ──


def _collect_pairs(
    zf: zipfile.ZipFile, infos: list[zipfile.ZipInfo]
) -> list[LecturePair]:
    """Group VTT + PDF entries into ``LecturePair`` records."""
    # group-key → {"vtt": [(zinfo, stem)...], "pdf": [...]}
    groups: dict[tuple[int, str], dict[str, list[tuple[zipfile.ZipInfo, str]]]] = (
        defaultdict(lambda: {"vtt": [], "pdf": []})
    )
    # Running total of actually-read bytes (trust nothing the header says).
    read_total = 0

    for zinfo in infos:
        if zinfo.is_dir():
            continue
        name = zinfo.filename
        lower = name.lower()
        if lower.endswith(".vtt"):
            kind = "vtt"
        elif lower.endswith(".pdf"):
            kind = "pdf"
        else:
            continue

        week_idx = _extract_week_index(name)
        stem = _normalize_stem(_basename_stem(name))
        groups[(week_idx, stem)][kind].append((zinfo, _basename_stem(name)))

    pairs: list[LecturePair] = []
    # Track per-week lecture ordering for groups without an explicit L\d index.
    fallback_counters: dict[int, int] = defaultdict(int)

    # Sort group keys so fallback lecture indices are stable.
    for (week_idx, _stem), bucket in sorted(groups.items(), key=lambda kv: kv[0]):
        vtts = sorted(bucket["vtt"], key=lambda t: t[0].filename.lower())
        pdfs = sorted(bucket["pdf"], key=lambda t: t[0].filename.lower())

        if len(vtts) > 1:
            logger.warning(
                "multi_vtt_detected week=%s stem=%s picked=%s dropped=%s",
                week_idx,
                _stem,
                vtts[0][0].filename,
                [v[0].filename for v in vtts[1:]],
            )
        if len(pdfs) > 1:
            logger.warning(
                "multi_pdf_detected week=%s stem=%s picked=%s dropped=%s",
                week_idx,
                _stem,
                pdfs[0][0].filename,
                [p[0].filename for p in pdfs[1:]],
            )

        vtt_zinfo, vtt_raw_stem = vtts[0] if vtts else (None, None)
        pdf_zinfo, pdf_raw_stem = pdfs[0] if pdfs else (None, None)

        if vtt_zinfo is None and pdf_zinfo is None:
            continue  # defensive; groups always have at least one side

        raw_stem_for_meta = vtt_raw_stem or pdf_raw_stem or _stem
        lecture_idx = _extract_lecture_index(raw_stem_for_meta)
        if lecture_idx is None:
            fallback_counters[week_idx] += 1
            lecture_idx = fallback_counters[week_idx]

        vtt_bytes, read_total = _read_entry(zf, vtt_zinfo, read_total)
        pdf_bytes, read_total = _read_entry(zf, pdf_zinfo, read_total)

        pairs.append(
            LecturePair(
                week_index=week_idx,
                lecture_index=lecture_idx,
                title=_title_from_stem(raw_stem_for_meta),
                vtt_path=vtt_zinfo.filename if vtt_zinfo else None,
                pdf_path=pdf_zinfo.filename if pdf_zinfo else None,
                vtt_bytes=vtt_bytes,
                pdf_bytes=pdf_bytes,
            )
        )

    return pairs


def _read_entry(
    zf: zipfile.ZipFile, zinfo: zipfile.ZipInfo | None, running_total: int
) -> tuple[bytes | None, int]:
    """Read one ZIP entry while enforcing the running uncompressed-size cap."""
    if zinfo is None:
        return None, running_total
    data = zf.read(zinfo)
    running_total += len(data)
    if running_total > _MAX_UNCOMPRESSED_BYTES:
        raise CourseraAdapterError(
            reason=(
                f"uncompressed size cap exceeded during extraction: "
                f"{running_total} > {_MAX_UNCOMPRESSED_BYTES} bytes (zip bomb?)"
            ),
            hint="Upload a smaller subset.",
        )
    return data, running_total


# ── Filename helpers ──


def _basename_stem(path: str) -> str:
    """Return the filename stem (no directory, no extension)."""
    tail = path.replace("\\", "/").rsplit("/", 1)[-1]
    dot = tail.rfind(".")
    return tail[:dot] if dot > 0 else tail


def _normalize_stem(stem: str) -> str:
    """Lowercase + strip Coursera-style suffixes used for pair matching."""
    s = stem.lower()
    changed = True
    while changed:
        changed = False
        for suffix in _STEM_SUFFIXES:
            if s.endswith(suffix):
                s = s[: -len(suffix)]
                changed = True
    return s.strip()


def _extract_week_index(path: str) -> int:
    """Infer 1-based week index from a path component like ``Week-1``."""
    parts = path.replace("\\", "/").split("/")
    for comp in parts[:-1]:  # skip the filename itself
        m = _WEEK_RE.match(comp.strip())
        if m:
            return int(m.group(1))
    return 1  # fallback: single-week course


def _extract_lecture_index(stem: str) -> int | None:
    """Infer 1-based lecture index from an ``L1`` / ``Lecture 2`` prefix."""
    m = _LECTURE_RE.search(stem)
    if m:
        return int(m.group(1))
    return None


def _title_from_stem(stem: str) -> str:
    """Derive a human-readable lecture title from the raw filename stem."""
    cleaned = re.sub(r"[_\-]+", " ", stem).strip()
    return cleaned or stem


# ── VTT → plain text (T2) ──

# Matches HTML/VTT inline tags: <v Speaker>, <i>, </i>, <c.classname>, <00:00:01.000>
_VTT_TAG_RE = re.compile(r"<[^>]+>")
# Matches a VTT cue timing line, e.g. "00:00:01.000 --> 00:00:05.000 ..."
_VTT_TIMING_RE = re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\.\d{3}\s*-->\s*")


def vtt_to_text(vtt_bytes: bytes) -> str:
    """Decode a VTT file to plain text with timestamps and speaker tags stripped."""
    if not vtt_bytes:
        return ""

    decoded = vtt_bytes.decode("utf-8", errors="replace")

    try:
        import webvtt  # local import keeps module import cheap when unused

        captions = webvtt.read_buffer(io.StringIO(decoded))
        lines: list[str] = []
        for cue in captions:
            text = _VTT_TAG_RE.sub("", cue.text).strip()
            if text:
                lines.append(text)
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001 — webvtt-py raises varied MalformedFileError/MalformedCaptionError
        logger.warning("webvtt_parse_fallback reason=%s", str(e))
        return _vtt_regex_fallback(decoded)


def _vtt_regex_fallback(decoded: str) -> str:
    """Best-effort regex parse used when webvtt-py rejects the file."""
    lines: list[str] = []
    in_note = False
    for raw in decoded.splitlines():
        line = raw.strip()
        if not line:
            in_note = False
            continue
        if line.startswith("WEBVTT"):
            continue
        if line.startswith("NOTE"):
            in_note = True
            continue
        if in_note:
            continue  # skip NOTE block body until blank line
        if _VTT_TIMING_RE.match(line):
            continue
        stripped = _VTT_TAG_RE.sub("", line).strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)


# ── Lecture markdown merge (T2) ──

_SLUG_NONALNUM_RE = re.compile(r"[^a-z0-9]+")


def merge_lecture_markdown(pair: LecturePair) -> tuple[str, bytes]:
    """Merge a lecture's VTT transcript + PDF slides into one ``.coursera.md`` blob."""
    slides_text = _extract_pdf_text(pair.pdf_bytes) if pair.pdf_bytes else ""
    transcript_text = vtt_to_text(pair.vtt_bytes) if pair.vtt_bytes else ""

    sections: list[str] = [f"## {pair.title}"]
    if slides_text.strip():
        sections.append(f"### Slides\n{slides_text.strip()}")
    if transcript_text.strip():
        sections.append(f"### Transcript\n{transcript_text.strip()}")

    markdown = "\n\n".join(sections) + "\n"
    slug = _slugify(pair.title, pair.week_index, pair.lecture_index)
    filename = f"{slug}.coursera.md"
    return filename, markdown.encode("utf-8")


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from in-memory PDF bytes by delegating to the shared fallback."""
    # `_extract_pdf_fallback` is path-based; spill bytes to a temp .pdf so we
    # can reuse the hardened Marker→pypdf chain without duplicating logic.
    from services.ingestion.document_loader_formats import _extract_pdf_fallback

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    try:
        _title, text = _extract_pdf_fallback(tmp_path)
        return text or ""
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _slugify(title: str, week_index: int, lecture_index: int) -> str:
    """Slugify a lecture title; fall back to ``lecture-wN-lM`` when empty."""
    slug = _SLUG_NONALNUM_RE.sub("-", title.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        return f"lecture-w{week_index}-l{lecture_index}"
    return slug
