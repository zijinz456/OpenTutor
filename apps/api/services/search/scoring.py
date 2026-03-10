"""Query decomposition, tokenization, and document scoring utilities.

Extracted from hybrid.py — provides the building blocks for
keyword matching, coverage analysis, and signal-based reranking.
"""

import re

# RRF constant (standard value from literature)
RRF_K = 60

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_ASCII_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{1,}")


def rrf_score(rank: int) -> float:
    """Reciprocal Rank Fusion score: 1/(k + rank)."""
    return 1.0 / (RRF_K + rank)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def decompose_search_query(query: str, max_facets: int = 4) -> list[str]:
    """Split complex study questions into focused retrieval facets."""
    normalized = " ".join((query or "").strip().split())
    if not normalized:
        return []

    facets: list[str] = []
    seen: set[str] = set()

    def _push(candidate: str) -> None:
        value = " ".join(candidate.strip().split())
        if len(value) < 4:
            return
        lowered = value.lower()
        if lowered == normalized.lower() or lowered in seen:
            return
        seen.add(lowered)
        facets.append(value)

    for quoted in re.findall(r'"([^"]+)"', normalized):
        _push(quoted)

    parts = re.split(r"\b(?:and|or|vs|versus)\b|[;,/]", normalized, flags=re.IGNORECASE)
    for part in parts:
        _push(part)

    salient = _tokenize_query(normalized)
    if len(salient) >= 4:
        _push(" ".join(salient[:2]))
        _push(" ".join(salient[2:4]))

    return facets[:max_facets]


def _tokenize_query(query: str) -> list[str]:
    """Extract mixed English/CJK search terms without relying on whitespace."""
    terms: list[str] = []
    seen: set[str] = set()

    def _push(term: str) -> None:
        value = term.strip().lower()
        if len(value) < 2 or value in seen:
            return
        seen.add(value)
        terms.append(value)

    for match in _ASCII_TERM_RE.finditer(query):
        _push(match.group(0))

    for segment in _CJK_RE.findall(query):
        _push(segment)
        if len(segment) <= 2:
            continue
        for size in (2, 3):
            if len(segment) < size:
                continue
            for idx in range(len(segment) - size + 1):
                _push(segment[idx : idx + size])

    if not terms and query.strip():
        _push(query[:100])
    return terms[:12]


def _normalize_source_score(source: str, raw_score: float) -> float:
    if raw_score <= 0:
        return 0.0
    if source == "vector":
        return max(0.0, min(raw_score, 1.0))
    if source in {"bm25", "keyword", "tree"}:
        return min(raw_score / 5.0, 1.0)
    return min(raw_score / 5.0, 1.0)


def _facet_match_ratio(text: str, facet: str) -> float:
    normalized_text = _normalize_text(text)
    normalized_facet = _normalize_text(facet)
    if not normalized_text or not normalized_facet:
        return 0.0
    if normalized_facet in normalized_text:
        return 1.0
    facet_terms = _tokenize_query(normalized_facet)
    if not facet_terms:
        return 0.0
    matched = sum(1 for term in facet_terms if term in normalized_text)
    return matched / len(facet_terms)


def _document_coverage_details(doc: dict, query: str, facets: list[str]) -> dict[str, object]:
    title = str(doc.get("title") or "")
    content = str(doc.get("content") or "")
    combined = f"{title}\n{content}"
    evidence_terms = _tokenize_query(query)
    matched_terms = [term for term in evidence_terms if term in _normalize_text(combined)]
    matched_facets = [facet for facet in facets if _facet_match_ratio(combined, facet) >= 0.6]
    evidence_coverage = len(set(matched_terms)) / max(len(set(evidence_terms)), 1) if evidence_terms else 0.0
    facet_coverage = len(matched_facets) / max(len(facets), 1) if facets else 0.0
    coverage_score = round((evidence_coverage * 0.03) + (facet_coverage * 0.028), 6)
    return {
        "matched_terms": matched_terms[:10],
        "matched_facets": matched_facets[:6],
        "evidence_coverage": round(evidence_coverage, 3),
        "facet_coverage": round(facet_coverage, 3),
        "coverage_score": coverage_score,
    }


def _document_signal_score(doc: dict, query: str, terms: list[str]) -> float:
    """Compute lightweight lexical/structural relevance for post-fusion reranking."""
    if not terms:
        return 0.0

    title = _normalize_text(str(doc.get("title") or ""))
    content = _normalize_text(str(doc.get("content") or ""))
    normalized_query = _normalize_text(query)

    title_hits = sum(1 for term in terms if term in title)
    content_hits = sum(1 for term in terms if term in content)
    unique_hits = sum(1 for term in terms if term in title or term in content)
    term_count = max(len(terms), 1)
    coverage = unique_hits / term_count
    title_ratio = title_hits / term_count
    content_ratio = content_hits / term_count

    phrase_in_title = bool(normalized_query and normalized_query in title)
    phrase_in_content = bool(normalized_query and normalized_query in content)

    level = int(doc.get("level") or 0)
    level_boost = max(0.0, 1.0 - (level * 0.12))
    source_score = _normalize_source_score(str(doc.get("source") or ""), float(doc.get("score") or 0.0))

    signal = 0.0
    signal += coverage * 0.03
    signal += title_ratio * 0.025
    signal += content_ratio * 0.018
    signal += source_score * 0.015
    signal += level_boost * 0.01
    if phrase_in_title:
        signal += 0.03
    if phrase_in_content:
        signal += 0.02
    return round(signal, 6)
