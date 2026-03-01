"""Knowledge graph builder — content tree + prerequisite DAG + path recommendations.

Builds D3-compatible graph format combining:
1. Hierarchical content tree (parent-child "contains" edges)
2. Prerequisite DAG from KnowledgePoints ("requires" edges)
3. Dynamic relationships from graph_memory ("related_to", "confused_with", etc.)
4. Path recommendations based on student's mastery gaps
"""

import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.content import CourseContentTree
from models.knowledge_graph import KnowledgePoint
from models.memory import ConversationMemory
from models.progress import LearningProgress

logger = logging.getLogger(__name__)


async def build_knowledge_graph(
    db: AsyncSession,
    course_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> dict:
    """Build a comprehensive knowledge graph combining content tree and prerequisites.

    Returns D3-compatible format: {nodes: [...], edges: [...], recommendations: [...]}.
    """
    # 1. Fetch content tree nodes
    tree_result = await db.execute(
        select(CourseContentTree)
        .where(CourseContentTree.course_id == course_id)
        .order_by(CourseContentTree.level, CourseContentTree.order_index)
    )
    tree_nodes = tree_result.scalars().all()

    # 2. Fetch knowledge points (prerequisite DAG)
    kp_result = await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.course_id == course_id)
    )
    knowledge_points = list(kp_result.scalars().all())

    # 3. Fetch dynamic graph relationships from memory
    dynamic_edges = []
    if user_id:
        mem_result = await db.execute(
            select(ConversationMemory)
            .where(
                ConversationMemory.user_id == user_id,
                ConversationMemory.course_id == course_id,
                ConversationMemory.category == "Relation",
            )
            .limit(100)
        )
        for mem in mem_result.scalars().all():
            meta = mem.metadata_json or {}
            if meta.get("source_entity") and meta.get("target_entity"):
                dynamic_edges.append({
                    "source_name": meta["source_entity"],
                    "target_name": meta["target_entity"],
                    "type": meta.get("relation_type", "related_to"),
                })

    # 4. Fetch progress data
    progress_map: dict[str, dict] = {}
    if user_id:
        prog_result = await db.execute(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        )
        for p in prog_result.scalars().all():
            if p.content_node_id:
                progress_map[str(p.content_node_id)] = {
                    "status": p.status,
                    "mastery_score": p.mastery_score,
                    "gap_type": p.gap_type,
                }

    # Build nodes and edges
    nodes = []
    edges = []
    node_ids = set()

    # Content tree nodes
    for node in tree_nodes:
        node_id = str(node.id)
        node_ids.add(node_id)
        progress = progress_map.get(node_id, {"status": "not_started", "mastery_score": 0.0})

        size = max(8, 20 - node.level * 4)
        mastery = progress.get("mastery_score", 0.0)
        gap_type = progress.get("gap_type")

        if mastery >= 0.8:
            color = "#22c55e"  # green - mastered
        elif mastery >= 0.4:
            color = "#3b82f6"  # blue - reviewed
        elif mastery > 0:
            color = "#eab308"  # yellow - in progress
        else:
            color = "#9ca3af"  # gray - not started

        nodes.append({
            "id": node_id,
            "label": node.title,
            "type": "content",
            "level": node.level,
            "size": size,
            "color": color,
            "status": progress.get("status", "not_started"),
            "mastery": mastery,
            "gap_type": gap_type,
        })

        if node.parent_id:
            edges.append({
                "source": str(node.parent_id),
                "target": node_id,
                "type": "contains",
            })

    # Knowledge point nodes + prerequisite edges
    kp_map = {str(kp.id): kp for kp in knowledge_points}
    kp_name_to_id: dict[str, str] = {}

    for kp in knowledge_points:
        kp_id = str(kp.id)
        if kp_id not in node_ids:
            mastery = kp.mastery_level / 100.0

            if mastery >= 0.8:
                color = "#22c55e"
            elif mastery >= 0.4:
                color = "#3b82f6"
            elif mastery > 0:
                color = "#eab308"
            else:
                color = "#9ca3af"

            nodes.append({
                "id": kp_id,
                "label": kp.name,
                "type": "knowledge_point",
                "level": -1,
                "size": 12,
                "color": color,
                "status": "mastered" if mastery >= 0.7 else "in_progress" if mastery > 0 else "not_started",
                "mastery": mastery,
                "gap_type": None,
            })
            node_ids.add(kp_id)

        kp_name_to_id[kp.name.lower()] = kp_id

        # Prerequisite edges
        for prereq_id in (kp.prerequisites or []):
            prereq_id = str(prereq_id)
            if prereq_id in kp_map:
                edges.append({
                    "source": prereq_id,
                    "target": kp_id,
                    "type": "requires",
                })

        # Link to source content node
        if kp.source_content_node_id:
            source_id = str(kp.source_content_node_id)
            if source_id in node_ids:
                edges.append({
                    "source": source_id,
                    "target": kp_id,
                    "type": "defines",
                })

    # Dynamic relationship edges (from graph_memory)
    for de in dynamic_edges:
        src = kp_name_to_id.get(de["source_name"].lower())
        tgt = kp_name_to_id.get(de["target_name"].lower())
        if src and tgt:
            edges.append({
                "source": src,
                "target": tgt,
                "type": de["type"],
            })

    # 5. Generate recommendations
    recommendations = _generate_recommendations(knowledge_points, progress_map, kp_map)

    return {
        "nodes": nodes,
        "edges": edges,
        "recommendations": recommendations,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "content_nodes": len(tree_nodes),
            "knowledge_points": len(knowledge_points),
            "dynamic_relations": len(dynamic_edges),
            "levels": max((n.level for n in tree_nodes), default=0) + 1 if tree_nodes else 0,
        },
    }


def _generate_recommendations(
    knowledge_points: list[KnowledgePoint],
    progress_map: dict[str, dict],
    kp_map: dict[str, KnowledgePoint],
) -> list[dict]:
    """Generate study recommendations based on knowledge graph gaps.

    Prioritizes:
    1. Unmastered prerequisites of topics the student is working on
    2. Topics in the Zone of Proximal Development (partially mastered)
    3. Topics with gap_type = "fundamental_gap" (highest priority)
    """
    recommendations = []

    for kp in knowledge_points:
        kp_id = str(kp.id)
        mastery = kp.mastery_level / 100.0

        if mastery >= 0.7:
            continue  # Already mastered

        # Check prerequisite readiness
        unmet_prereqs = []
        for prereq_id in (kp.prerequisites or []):
            prereq_id = str(prereq_id)
            prereq = kp_map.get(prereq_id)
            if prereq and prereq.mastery_level < 70:
                unmet_prereqs.append({
                    "id": prereq_id,
                    "name": prereq.name,
                    "mastery": prereq.mastery_level / 100.0,
                })

        # Priority scoring
        priority = 0.0

        # Check if this is linked to a content node with a gap
        if kp.source_content_node_id:
            prog = progress_map.get(str(kp.source_content_node_id), {})
            gap = prog.get("gap_type")
            if gap == "fundamental_gap":
                priority += 3.0
            elif gap == "transfer_gap":
                priority += 2.0
            elif gap == "trap_vulnerability":
                priority += 1.0

        # ZPD bonus: partially mastered topics are easier to advance
        if 0.2 <= mastery <= 0.6:
            priority += 1.5

        # Penalty if prerequisites not met
        if unmet_prereqs:
            priority -= 0.5

        if priority > 0:
            recommendations.append({
                "id": kp_id,
                "name": kp.name,
                "mastery": mastery,
                "priority": round(priority, 2),
                "reason": _get_recommendation_reason(mastery, unmet_prereqs, progress_map, kp),
                "unmet_prerequisites": unmet_prereqs,
                "action": "review_prerequisites" if unmet_prereqs else "study",
            })

    # Sort by priority
    recommendations.sort(key=lambda r: -r["priority"])
    return recommendations[:10]


def _get_recommendation_reason(
    mastery: float,
    unmet_prereqs: list[dict],
    progress_map: dict[str, dict],
    kp: KnowledgePoint,
) -> str:
    """Generate a human-readable reason for the recommendation."""
    if unmet_prereqs:
        names = ", ".join(p["name"] for p in unmet_prereqs[:3])
        return f"Review prerequisites first: {names}"
    if kp.source_content_node_id:
        gap = progress_map.get(str(kp.source_content_node_id), {}).get("gap_type")
        if gap == "fundamental_gap":
            return "Fundamental knowledge gap detected — focus on core concepts"
        if gap == "transfer_gap":
            return "Can recall but struggles to apply — practice with varied problems"
        if gap == "trap_vulnerability":
            return "Vulnerable to common traps — review edge cases"
    if 0.2 <= mastery <= 0.6:
        return "In your Zone of Proximal Development — ready to advance with practice"
    return "Not yet started — begin with foundational material"
