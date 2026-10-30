"""Knowledge graph builders for frontend graph rendering."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.content import CourseContentTree
from models.progress import LearningProgress
from services.loom_flags import loom_enabled
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


def _node_payload(
    *, node_id: str, label: str, node_type: str, level: int, mastery: float,
    gap_type: str | None = None,
) -> dict[str, Any]:
    status = _status_from_mastery(mastery)
    size = max(8, min(24, int(10 + mastery * 14)))
    return {
        "id": node_id,
        "label": label,
        "type": node_type,
        "level": level,
        "size": size,
        "color": _color_from_status(status),
        "status": status,
        "mastery": round(mastery, 3),
        "gap_type": gap_type,
    }


async def build_content_tree_graph(
    db: AsyncSession,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    """Graph from the content tree + learning_progress (no LOOM needed).

    Nodes are content tree entries coloured by their ledger mastery; edges
    follow the parent → child structure of the course.
    """
    result = await db.execute(
        select(CourseContentTree)
        .where(CourseContentTree.course_id == course_id)
        .order_by(CourseContentTree.level, CourseContentTree.order_index)
    )
    tree_nodes = list(result.scalars().all())
    result = await db.execute(
        select(LearningProgress).where(
            LearningProgress.user_id == user_id,
            LearningProgress.course_id == course_id,
            LearningProgress.content_node_id.isnot(None),
        )
    )
    progress_by_node = {p.content_node_id: p for p in result.scalars().all()}

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    ids = {n.id for n in tree_nodes}
    for tn in tree_nodes:
        progress = progress_by_node.get(tn.id)
        nodes.append(_node_payload(
            node_id=str(tn.id),
            label=tn.title or "Untitled",
            node_type="content",
            level=int(tn.level or 0) + 1,
            mastery=float(progress.mastery_score) if progress else 0.0,
            gap_type=progress.gap_type if progress else None,
        ))
        if tn.parent_id and tn.parent_id in ids:
            edges.append({"source": str(tn.parent_id), "target": str(tn.id), "type": "contains"})

    return {"course_id": str(course_id), "nodes": nodes, "edges": edges}


async def build_knowledge_graph(
    db: AsyncSession,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    """Return a D3-friendly knowledge graph payload for the web app.

    With LOOM enabled the graph is the concept graph with concept_mastery;
    otherwise (the default) it is the content tree with learning_progress
    mastery, so the page is useful without the experimental layer.
    """
    if not loom_enabled():
        return await build_content_tree_graph(db, course_id, user_id)

    graph = await get_mastery_graph(db, user_id, course_id)
    if not graph.get("nodes"):
        return await build_content_tree_graph(db, course_id, user_id)

    raw_nodes = graph.get("nodes", [])
    raw_edges = graph.get("edges", [])

    nodes: list[dict[str, Any]] = []
    for raw in raw_nodes:
        nodes.append(_node_payload(
            node_id=str(raw.get("id")),
            label=str(raw.get("name") or "Untitled Concept"),
            node_type="concept",
            level=int(raw.get("bloom_level") or 1),
            mastery=float(raw.get("mastery") or 0.0),
        ))

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
