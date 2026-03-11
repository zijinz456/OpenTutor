"""Knowledge graph builders for frontend graph rendering."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.loom_graph import get_mastery_graph


def _status_from_mastery(mastery: float) -> str:
    if mastery >= 0.85:
        return "mastered"
    if mastery >= 0.6:
        return "reviewed"
    if mastery > 0:
        return "in_progress"
    return "not_started"


def _color_from_status(status: str) -> str:
    if status == "mastered":
        return "#22C55E"
    if status == "reviewed":
        return "#3B82F6"
    if status == "in_progress":
        return "#F59E0B"
    return "#94A3B8"


async def build_knowledge_graph(
    db: AsyncSession,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    """Return a D3-friendly knowledge graph payload for the web app."""
    graph = await get_mastery_graph(db, user_id, course_id)

    raw_nodes = graph.get("nodes", [])
    raw_edges = graph.get("edges", [])

    nodes: list[dict[str, Any]] = []
    for raw in raw_nodes:
        mastery = float(raw.get("mastery") or 0.0)
        status = _status_from_mastery(mastery)
        level = int(raw.get("bloom_level") or 1)
        size = max(8, min(24, int(10 + mastery * 14)))
        nodes.append(
            {
                "id": str(raw.get("id")),
                "label": str(raw.get("name") or "Untitled Concept"),
                "type": "concept",
                "level": level,
                "size": size,
                "color": _color_from_status(status),
                "status": status,
                "mastery": round(mastery, 3),
                "gap_type": None,
            }
        )

    edges: list[dict[str, Any]] = []
    for raw in raw_edges:
        source = raw.get("source")
        target = raw.get("target")
        if source is None or target is None:
            continue
        edges.append(
            {
                "source": str(source),
                "target": str(target),
                "type": str(raw.get("type") or "related"),
            }
        )

    return {
        "course_id": str(course_id),
        "nodes": nodes,
        "edges": edges,
    }
