import type { KnowledgeGraphNode, KnowledgeGraphEdge } from "@/lib/api";

export const WIDTH = 800;
export const HEIGHT = 600;
export const REPULSION = 3000;
export const SPRING_K = 0.005;
export const SPRING_LEN = 120;
export const DAMPING = 0.85;
export const MAX_ITER = 100;

export interface SimNode extends KnowledgeGraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

export function buildFocusedGraph(
  nodes: KnowledgeGraphNode[],
  edges: KnowledgeGraphEdge[],
  focusTerms?: string[],
  maxNodes = 20,
): { nodes: KnowledgeGraphNode[]; edges: KnowledgeGraphEdge[] } {
  const normalizedTerms = (focusTerms ?? [])
    .map((term) => term.trim().toLowerCase())
    .filter((term) => term.length >= 2);
  if (normalizedTerms.length === 0) {
    return { nodes, edges };
  }

  const seedIds = new Set(
    nodes
      .filter((node) =>
        normalizedTerms.some((term) => node.label.toLowerCase().includes(term)),
      )
      .map((node) => node.id),
  );

  // If no direct matches, fall back to the full graph.
  if (seedIds.size === 0) {
    return { nodes, edges };
  }

  const included = new Set(seedIds);
  for (const edge of edges) {
    if (seedIds.has(edge.source) || seedIds.has(edge.target)) {
      included.add(edge.source);
      included.add(edge.target);
    }
  }

  let focusedNodes = nodes.filter((node) => included.has(node.id));
  let focusedEdges = edges.filter(
    (edge) => included.has(edge.source) && included.has(edge.target),
  );

  if (focusedNodes.length > maxNodes) {
    const prioritized = [...focusedNodes].sort((a, b) => {
      const aSeed = seedIds.has(a.id) ? 0 : 1;
      const bSeed = seedIds.has(b.id) ? 0 : 1;
      if (aSeed !== bSeed) return aSeed - bSeed;
      return a.mastery - b.mastery;
    });
    focusedNodes = prioritized.slice(0, maxNodes);
    const allowed = new Set(focusedNodes.map((node) => node.id));
    focusedEdges = focusedEdges.filter(
      (edge) => allowed.has(edge.source) && allowed.has(edge.target),
    );
  }

  return { nodes: focusedNodes, edges: focusedEdges };
}

export function runSimulationStep(
  nodes: SimNode[],
  edges: KnowledgeGraphEdge[],
  nodeMap: Map<string, number>,
): SimNode[] {
  const nextNodes = nodes.map((n) => ({ ...n }));

  for (let i = 0; i < nextNodes.length; i++) {
    for (let j = i + 1; j < nextNodes.length; j++) {
      let dx = nextNodes[i].x - nextNodes[j].x;
      let dy = nextNodes[i].y - nextNodes[j].y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = REPULSION / (dist * dist);
      dx = (dx / dist) * force;
      dy = (dy / dist) * force;
      nextNodes[i].vx += dx;
      nextNodes[i].vy += dy;
      nextNodes[j].vx -= dx;
      nextNodes[j].vy -= dy;
    }
  }

  for (const edge of edges) {
    const si = nodeMap.get(edge.source);
    const ti = nodeMap.get(edge.target);
    if (si === undefined || ti === undefined) continue;
    const dx = nextNodes[ti].x - nextNodes[si].x;
    const dy = nextNodes[ti].y - nextNodes[si].y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const displacement = dist - SPRING_LEN;
    const fx = SPRING_K * displacement * (dx / dist);
    const fy = SPRING_K * displacement * (dy / dist);
    nextNodes[si].vx += fx;
    nextNodes[si].vy += fy;
    nextNodes[ti].vx -= fx;
    nextNodes[ti].vy -= fy;
  }

  for (const node of nextNodes) {
    node.vx *= DAMPING;
    node.vy *= DAMPING;
    node.x += node.vx;
    node.y += node.vy;
    node.x = Math.max(30, Math.min(WIDTH - 30, node.x));
    node.y = Math.max(30, Math.min(HEIGHT - 30, node.y));
  }

  return nextNodes;
}
