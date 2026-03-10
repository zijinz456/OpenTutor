"""Transfer learning detector.

Detects when mastery of a concept in one course accelerates learning of
related concepts in other courses, leveraging LOOM's cross-course
knowledge graph edges.

Reference: Barnett & Ceci (2002) taxonomy of transfer learning
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import ConceptMastery, KnowledgeEdge, KnowledgeNode

logger = logging.getLogger(__name__)

# Minimum mastery to consider a concept "mastered" for transfer detection
MASTERY_THRESHOLD = 0.7
# Minimum mastery gain to consider as "surprising" (faster than expected)
SURPRISE_GAIN_THRESHOLD = 0.15


async def detect_transfer_opportunities(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[dict]:
    """Detect cross-course transfer learning opportunities.

    Finds concept pairs where:
    1. A concept in course A is mastered
    2. A related concept in course B exists (via 'reinforces' edges)
    3. The concept in course B has low mastery

    Returns a list of transfer recommendations:
    [
        {
            "source_concept": str,
            "source_course_id": str,
            "source_mastery": float,
            "target_concept": str,
            "target_course_id": str,
            "target_mastery": float,
            "edge_type": str,
            "recommendation": str,
        }
    ]
    """
    # Find all cross-course 'reinforces' edges
    edges = await db.execute(
        select(KnowledgeEdge)
        .join(
            KnowledgeNode,
            KnowledgeEdge.source_id == KnowledgeNode.id,
        )
        .where(KnowledgeEdge.relation_type == "reinforces")
    )
    cross_edges = edges.scalars().all()

    if not cross_edges:
        return []

    # Collect all node IDs we need mastery for
    node_ids = set()
    for edge in cross_edges:
        node_ids.add(str(edge.source_id))
        node_ids.add(str(edge.target_id))

    # Fetch mastery for all relevant nodes
    masteries = await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == str(user_id),
            ConceptMastery.knowledge_node_id.in_(node_ids),
        )
    )
    mastery_map: dict[str, float] = {
        str(m.knowledge_node_id): m.mastery_score for m in masteries.scalars().all()
    }

    # Fetch node details for readable names
    nodes = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.id.in_(node_ids))
    )
    node_map: dict[str, KnowledgeNode] = {
        str(n.id): n for n in nodes.scalars().all()
    }

    recommendations = []
    for edge in cross_edges:
        source_id = str(edge.source_id)
        target_id = str(edge.target_id)

        source_mastery = mastery_map.get(source_id, 0.0)
        target_mastery = mastery_map.get(target_id, 0.0)

        source_node = node_map.get(source_id)
        target_node = node_map.get(target_id)

        if not source_node or not target_node:
            continue

        # Skip if both in the same course
        if source_node.course_id == target_node.course_id:
            continue

        # Transfer opportunity: source mastered, target not
        if source_mastery >= MASTERY_THRESHOLD and target_mastery < MASTERY_THRESHOLD:
            recommendations.append({
                "source_concept": source_node.name,
                "source_course_id": str(source_node.course_id),
                "source_mastery": round(source_mastery, 2),
                "target_concept": target_node.name,
                "target_course_id": str(target_node.course_id),
                "target_mastery": round(target_mastery, 2),
                "edge_type": edge.relation_type,
                "recommendation": (
                    f"Your mastery of '{source_node.name}' can help you learn "
                    f"'{target_node.name}' faster. Consider studying it next."
                ),
            })

    # Sort by target mastery (lowest first — biggest opportunity)
    recommendations.sort(key=lambda r: r["target_mastery"])
    return recommendations[:20]  # Cap at 20 recommendations
