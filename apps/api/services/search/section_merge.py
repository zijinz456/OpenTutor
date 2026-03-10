"""Section-level hit merging and deduplication.

Collapses near-duplicate search hits from the same content section
into a single richer result with supporting snippets and evidence summaries.
"""

from services.search.scoring import _normalize_text


def _section_group_key(doc: dict) -> str:
    source_file = str(doc.get("source_file") or "")
    parent_id = str(doc.get("parent_id") or "")
    title = _normalize_text(str(doc.get("title") or ""))
    if parent_id:
        return f"{source_file}|{parent_id}"
    return f"{source_file}|{title[:120]}"


def _merge_section_hits(results: list[dict], limit: int) -> list[dict]:
    """Collapse near-duplicate hits from the same section into one richer result."""
    merged: list[dict] = []
    merged_by_key: dict[str, dict] = {}

    for doc in results:
        key = _section_group_key(doc)
        existing = merged_by_key.get(key)
        if existing is None:
            primary = dict(doc)
            primary["section_key"] = key
            primary["section_hit_count"] = 1
            primary["supporting_hit_ids"] = []
            primary["supporting_snippets"] = []
            merged_by_key[key] = primary
            merged.append(primary)
            continue

        existing["section_hit_count"] = int(existing.get("section_hit_count") or 1) + 1
        supporting_ids = list(existing.get("supporting_hit_ids") or [])
        if doc.get("id") and doc.get("id") not in supporting_ids and doc.get("id") != existing.get("id"):
            supporting_ids.append(str(doc["id"]))
        existing["supporting_hit_ids"] = supporting_ids[:5]

        snippets = list(existing.get("supporting_snippets") or [])
        snippet = str(doc.get("content") or "")[:180].strip()
        if snippet and snippet not in snippets:
            snippets.append(snippet)
        existing["supporting_snippets"] = snippets[:3]

        existing["source_hits"] = sorted({
            *(existing.get("source_hits") or []),
            *(doc.get("source_hits") or []),
        })
        existing["matched_terms"] = sorted({
            *(existing.get("matched_terms") or []),
            *(doc.get("matched_terms") or []),
        })[:12]
        existing["matched_facets"] = sorted({
            *(existing.get("matched_facets") or []),
            *(doc.get("matched_facets") or []),
        })[:8]
        existing["evidence_coverage"] = round(
            max(float(existing.get("evidence_coverage") or 0.0), float(doc.get("evidence_coverage") or 0.0)),
            3,
        )
        existing["facet_coverage"] = round(
            max(float(existing.get("facet_coverage") or 0.0), float(doc.get("facet_coverage") or 0.0)),
            3,
        )
        existing["coverage_score"] = round(
            max(float(existing.get("coverage_score") or 0.0), float(doc.get("coverage_score") or 0.0))
            + (int(existing.get("section_hit_count") or 1) - 1) * 0.006,
            6,
        )
        existing["hybrid_score"] = round(
            max(float(existing.get("hybrid_score") or 0.0), float(doc.get("hybrid_score") or 0.0))
            + (int(existing.get("section_hit_count") or 1) - 1) * 0.008,
            6,
        )

        if float(doc.get("hybrid_score") or 0.0) > float(existing.get("hybrid_score") or 0.0):
            previous_primary_id = existing.get("id")
            if previous_primary_id and previous_primary_id != doc.get("id") and previous_primary_id not in existing["supporting_hit_ids"]:
                existing["supporting_hit_ids"] = [*existing["supporting_hit_ids"], str(previous_primary_id)][:5]
            existing["id"] = doc.get("id")
            existing["title"] = doc.get("title")
            existing["content"] = doc.get("content")
            existing["level"] = doc.get("level")
            existing["score"] = doc.get("score")
            existing["source"] = doc.get("source")
            existing["rrf_score"] = doc.get("rrf_score")
            existing["signal_score"] = doc.get("signal_score")

    merged.sort(
        key=lambda item: (
            float(item.get("hybrid_score") or 0.0),
            int(item.get("section_hit_count") or 1),
            float(item.get("rrf_score") or 0.0),
        ),
        reverse=True,
    )
    top = merged[:limit]
    for item in top:
        summary_bits: list[str] = []
        matched_facets = list(item.get("matched_facets") or [])
        matched_terms = list(item.get("matched_terms") or [])
        supporting_snippets = list(item.get("supporting_snippets") or [])
        if matched_facets:
            summary_bits.append(f"Matches: {', '.join(matched_facets[:2])}")
        elif matched_terms:
            summary_bits.append(f"Key terms: {', '.join(matched_terms[:4])}")
        if supporting_snippets:
            summary_bits.append(supporting_snippets[0][:140])
        else:
            preview = str(item.get("content") or "").strip()
            if preview:
                summary_bits.append(preview[:140])
        item["evidence_summary"] = " — ".join(bit for bit in summary_bits if bit)[:320]
    return top
