"""Learning path optimization using topological sort + critical path analysis.

Given a DAG of KnowledgePoints (via prerequisites field), this module:
1. Topological sort: determine valid study order respecting prerequisites
2. Critical path: find the longest dependency chain (bottleneck)
3. Adaptive sequencing: prioritize weak areas, skip mastered topics
4. Time estimation: estimate study time based on mastery gaps

References:
- Kahn's algorithm for topological sort (BFS-based, detects cycles)
- CPM (Critical Path Method) for project scheduling
- Zone of Proximal Development: prioritize topics just beyond current mastery
"""

import logging
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import KnowledgePoint
from models.progress import LearningProgress

logger = logging.getLogger(__name__)

# Estimated study time per mastery gap percentage point (minutes)
MINUTES_PER_MASTERY_POINT = 2.0
MASTERY_THRESHOLD = 0.7  # Consider mastered above this


@dataclass
class PathNode:
    """A node in the learning path."""
    id: str
    name: str
    mastery: float
    prerequisites: list[str]
    estimated_minutes: float
    priority: float  # Higher = should study first
    on_critical_path: bool = False
    depth: int = 0  # Distance from root in DAG


@dataclass
class LearningPath:
    """Optimized learning path result."""
    ordered_nodes: list[PathNode]
    critical_path: list[PathNode]
    total_estimated_minutes: float
    parallel_groups: list[list[str]]  # Groups of topics that can be studied in parallel
    skipped_mastered: int
    cycle_detected: bool = False


def _build_adjacency(
    knowledge_points: list[KnowledgePoint],
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, KnowledgePoint]]:
    """Build adjacency lists from KnowledgePoint prerequisites.

    Returns:
        - forward_edges: prerequisite → dependents (who depends on me)
        - reverse_edges: dependent → prerequisites (what do I depend on)
        - kp_map: id → KnowledgePoint
    """
    kp_map = {str(kp.id): kp for kp in knowledge_points}
    forward_edges: dict[str, list[str]] = defaultdict(list)
    reverse_edges: dict[str, list[str]] = defaultdict(list)

    for kp in knowledge_points:
        kp_id = str(kp.id)
        prereqs = kp.prerequisites or []
        for prereq_id in prereqs:
            prereq_id = str(prereq_id)
            if prereq_id in kp_map:
                forward_edges[prereq_id].append(kp_id)
                reverse_edges[kp_id].append(prereq_id)

    return forward_edges, reverse_edges, kp_map


def topological_sort(
    knowledge_points: list[KnowledgePoint],
) -> tuple[list[str], bool]:
    """Kahn's algorithm for topological sort.

    Returns (ordered_ids, has_cycle).
    If cycle detected, returns partial order + True.
    """
    forward_edges, reverse_edges, kp_map = _build_adjacency(knowledge_points)

    # Calculate in-degrees
    in_degree: dict[str, int] = {str(kp.id): 0 for kp in knowledge_points}
    for kp_id, prereqs in reverse_edges.items():
        in_degree[kp_id] = len(prereqs)

    # Initialize queue with zero in-degree nodes (no prerequisites)
    queue = deque(kp_id for kp_id, deg in in_degree.items() if deg == 0)
    ordered: list[str] = []

    while queue:
        node = queue.popleft()
        ordered.append(node)

        for dependent in forward_edges.get(node, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    has_cycle = len(ordered) < len(knowledge_points)
    return ordered, has_cycle


def critical_path(
    knowledge_points: list[KnowledgePoint],
    mastery_map: dict[str, float],
) -> list[str]:
    """Find the critical path (longest dependency chain weighted by study time).

    Uses dynamic programming on the topologically sorted DAG.
    Weight of each node = estimated study time based on mastery gap.
    """
    ordered, has_cycle = topological_sort(knowledge_points)
    if has_cycle:
        return []

    forward_edges, reverse_edges, kp_map = _build_adjacency(knowledge_points)

    # Weight = estimated study time for this node
    weight: dict[str, float] = {}
    for kp_id, kp in kp_map.items():
        mastery = mastery_map.get(kp_id, 0.0)
        gap = max(0, MASTERY_THRESHOLD - mastery)
        weight[kp_id] = gap * 100 * MINUTES_PER_MASTERY_POINT

    # DP: longest path from any root to each node
    dist: dict[str, float] = {kp_id: weight.get(kp_id, 0) for kp_id in ordered}
    predecessor: dict[str, str | None] = {kp_id: None for kp_id in ordered}

    for node in ordered:
        for dependent in forward_edges.get(node, []):
            candidate = dist[node] + weight.get(dependent, 0)
            if candidate > dist.get(dependent, 0):
                dist[dependent] = candidate
                predecessor[dependent] = node

    # Find the endpoint of the longest path
    if not dist:
        return []
    end_node = max(dist, key=lambda k: dist[k])

    # Trace back
    path: list[str] = []
    current: str | None = end_node
    while current is not None:
        path.append(current)
        current = predecessor[current]

    path.reverse()
    return path


def find_parallel_groups(
    knowledge_points: list[KnowledgePoint],
) -> list[list[str]]:
    """Find groups of knowledge points that can be studied in parallel.

    Each group contains nodes whose prerequisites are all in prior groups.
    This is equivalent to BFS levels in the DAG.
    """
    _, reverse_edges, kp_map = _build_adjacency(knowledge_points)

    in_degree: dict[str, int] = {str(kp.id): 0 for kp in knowledge_points}
    forward_edges: dict[str, list[str]] = defaultdict(list)

    for kp in knowledge_points:
        kp_id = str(kp.id)
        prereqs = kp.prerequisites or []
        for prereq_id in prereqs:
            prereq_id = str(prereq_id)
            if prereq_id in kp_map:
                forward_edges[prereq_id].append(kp_id)
                in_degree[kp_id] += 1

    # BFS by levels
    groups: list[list[str]] = []
    current_level = [kp_id for kp_id, deg in in_degree.items() if deg == 0]

    while current_level:
        groups.append(current_level)
        next_level: list[str] = []
        for node in current_level:
            for dep in forward_edges.get(node, []):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    next_level.append(dep)
        current_level = next_level

    return groups


async def optimize_learning_path(
    db: AsyncSession,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    skip_mastered: bool = True,
) -> dict:
    """Generate an optimized learning path for a course.

    Combines:
    1. Topological sort (prerequisite ordering)
    2. Critical path analysis (identify bottleneck chain)
    3. Mastery-aware prioritization (focus on gaps)
    4. Parallel group detection (what can be studied simultaneously)

    Returns a structured learning path with time estimates.
    """
    # Fetch all knowledge points for the course
    kp_result = await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.course_id == course_id)
    )
    knowledge_points = list(kp_result.scalars().all())

    if not knowledge_points:
        return {
            "path": [],
            "critical_path": [],
            "parallel_groups": [],
            "total_estimated_minutes": 0,
            "skipped_mastered": 0,
            "total_knowledge_points": 0,
        }

    # Fetch user's mastery levels
    progress_result = await db.execute(
        select(LearningProgress).where(
            LearningProgress.user_id == user_id,
            LearningProgress.course_id == course_id,
        )
    )
    progress_rows = progress_result.scalars().all()

    # Map content_node_id → mastery, then kp.source_content_node_id → mastery
    content_mastery: dict[str, float] = {}
    for p in progress_rows:
        if p.content_node_id:
            content_mastery[str(p.content_node_id)] = p.mastery_score

    mastery_map: dict[str, float] = {}
    for kp in knowledge_points:
        kp_id = str(kp.id)
        # Use KnowledgePoint's own mastery_level first, fall back to linked content node
        if kp.mastery_level > 0:
            mastery_map[kp_id] = kp.mastery_level / 100.0
        elif kp.source_content_node_id:
            mastery_map[kp_id] = content_mastery.get(str(kp.source_content_node_id), 0.0)
        else:
            mastery_map[kp_id] = 0.0

    # Topological sort
    ordered_ids, has_cycle = topological_sort(knowledge_points)
    kp_map = {str(kp.id): kp for kp in knowledge_points}

    # Critical path
    cp_ids = critical_path(knowledge_points, mastery_map)
    cp_set = set(cp_ids)

    # Parallel groups
    groups = find_parallel_groups(knowledge_points)

    # Compute depth for each node (BFS level in DAG)
    depth_map: dict[str, int] = {}
    for level, group in enumerate(groups):
        for kp_id in group:
            depth_map[kp_id] = level

    # Build path nodes
    skipped = 0
    path_nodes: list[dict] = []

    for kp_id in ordered_ids:
        kp = kp_map.get(kp_id)
        if not kp:
            continue

        mastery = mastery_map.get(kp_id, 0.0)

        # Skip mastered topics if requested
        if skip_mastered and mastery >= MASTERY_THRESHOLD:
            skipped += 1
            continue

        gap = max(0, MASTERY_THRESHOLD - mastery)
        est_minutes = round(gap * 100 * MINUTES_PER_MASTERY_POINT, 1)

        # Priority: higher for unmastered prereqs on critical path, ZPD sweet spot
        zpd_bonus = 1.0 if 0.3 <= mastery <= 0.6 else 0.5  # Zone of Proximal Dev
        critical_bonus = 1.5 if kp_id in cp_set else 1.0
        priority = round((1.0 - mastery) * zpd_bonus * critical_bonus, 3)

        path_nodes.append({
            "id": kp_id,
            "name": kp.name,
            "description": kp.description,
            "mastery": round(mastery, 3),
            "estimated_minutes": est_minutes,
            "priority": priority,
            "on_critical_path": kp_id in cp_set,
            "depth": depth_map.get(kp_id, 0),
            "prerequisites": [str(p) for p in (kp.prerequisites or []) if str(p) in kp_map],
        })

    # Sort by priority (highest first), then by depth (shallowest first)
    path_nodes.sort(key=lambda n: (-n["priority"], n["depth"]))

    # Critical path nodes (in order)
    cp_nodes = [
        {
            "id": kp_id,
            "name": kp_map[kp_id].name,
            "mastery": round(mastery_map.get(kp_id, 0.0), 3),
            "estimated_minutes": round(
                max(0, MASTERY_THRESHOLD - mastery_map.get(kp_id, 0.0)) * 100 * MINUTES_PER_MASTERY_POINT, 1
            ),
        }
        for kp_id in cp_ids
        if kp_id in kp_map
    ]

    total_minutes = sum(n["estimated_minutes"] for n in path_nodes)

    # Parallel groups with names
    named_groups = [
        [
            {"id": kp_id, "name": kp_map[kp_id].name}
            for kp_id in group
            if kp_id in kp_map
        ]
        for group in groups
    ]

    return {
        "path": path_nodes,
        "critical_path": cp_nodes,
        "critical_path_minutes": sum(n["estimated_minutes"] for n in cp_nodes),
        "parallel_groups": named_groups,
        "total_estimated_minutes": round(total_minutes, 1),
        "skipped_mastered": skipped,
        "total_knowledge_points": len(knowledge_points),
        "cycle_detected": has_cycle,
    }
