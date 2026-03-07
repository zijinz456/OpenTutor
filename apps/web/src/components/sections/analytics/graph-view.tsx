"use client";

import { useCallback, useEffect, useState } from "react";
import { useT } from "@/lib/i18n-context";
import {
  getKnowledgeGraph,
  type KnowledgeGraphNode,
  type KnowledgeGraphEdge,
} from "@/lib/api";

interface GraphViewProps {
  courseId: string;
  focusTerms?: string[];
  maxNodes?: number;
}

interface SimNode extends KnowledgeGraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

const WIDTH = 800;
const HEIGHT = 600;
const REPULSION = 3000;
const SPRING_K = 0.005;
const SPRING_LEN = 120;
const DAMPING = 0.85;
const MAX_ITER = 100;

function buildFocusedGraph(
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

export function GraphView({ courseId, focusTerms, maxNodes = 20 }: GraphViewProps) {
  const t = useT();
  const [nodes, setNodes] = useState<SimNode[]>([]);
  const [edges, setEdges] = useState<KnowledgeGraphEdge[]>([]);
  const [selected, setSelected] = useState<SimNode | null>(null);
  const [loading, setLoading] = useState(true);
  const [empty, setEmpty] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getKnowledgeGraph(courseId)
      .then((data) => {
        if (cancelled) return;
        const focused = buildFocusedGraph(
          data.nodes ?? [],
          data.edges ?? [],
          focusTerms,
          maxNodes,
        );

        if (!focused.nodes.length) {
          setEmpty(true);
          setLoading(false);
          return;
        }
        const cx = WIDTH / 2;
        const cy = HEIGHT / 2;
        const r = Math.min(WIDTH, HEIGHT) * 0.35;
        const simNodes: SimNode[] = focused.nodes.map((node, index) => {
          const angle = (2 * Math.PI * index) / focused.nodes.length;
          return {
            ...node,
            x: cx + r * Math.cos(angle),
            y: cy + r * Math.sin(angle),
            vx: 0,
            vy: 0,
          };
        });
        setEdges(focused.edges);
        setNodes(simNodes);
        setEmpty(false);
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) {
          setEmpty(true);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [courseId, focusTerms, maxNodes]);

  useEffect(() => {
    if (nodes.length === 0) return;
    let iter = 0;
    let frame: number;
    const nodeMap = new Map<string, number>();
    nodes.forEach((node, index) => nodeMap.set(node.id, index));

    const step = () => {
      if (iter >= MAX_ITER) return;
      iter++;
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

      setNodes([...nextNodes]);
      frame = requestAnimationFrame(step);
    };

    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- nodes identity changes every frame; depend only on length
  }, [nodes.length, edges]);

  const handleNodeClick = useCallback(
    (node: SimNode) => {
      setSelected(selected?.id === node.id ? null : node);
    },
    [selected],
  );

  if (loading) {
    return (
      <div
        className="flex-1 flex items-center justify-center p-8"
        data-testid="graph-panel"
      >
        <p className="text-xs text-muted-foreground">Loading graph...</p>
      </div>
    );
  }

  if (empty) {
    return (
      <div
        className="flex-1 flex flex-col items-center justify-center p-8 text-center"
        data-testid="graph-panel"
      >
        <h3 className="text-sm font-medium mb-1">{t("course.graph")}</h3>
        <p className="text-xs text-muted-foreground max-w-xs">
          Upload course materials to generate the knowledge graph
        </p>
      </div>
    );
  }

  const nodeById = new Map(nodes.map((node) => [node.id, node]));

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-testid="graph-panel">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full h-full min-h-0 bg-background"
      >
        {edges.map((edge) => {
          const source = nodeById.get(edge.source);
          const target = nodeById.get(edge.target);
          if (!source || !target) return null;
          return (
            <line
              key={`${edge.source}-${edge.target}`}
              x1={source.x}
              y1={source.y}
              x2={target.x}
              y2={target.y}
              stroke="var(--border, #ccc)"
              strokeWidth={1.5}
              strokeOpacity={0.5}
            />
          );
        })}
        {nodes.map((node) => (
          <g
            key={node.id}
            onClick={() => handleNodeClick(node)}
            className="cursor-pointer"
          >
            <circle
              cx={node.x}
              cy={node.y}
              r={Math.max(8, node.size ?? 12)}
              fill={`hsl(0 0% ${Math.round(20 + node.mastery * 60)}%)`}
              stroke={selected?.id === node.id ? "#fff" : "none"}
              strokeWidth={selected?.id === node.id ? 3 : 0}
              opacity={0.9}
            />
            <text
              x={node.x}
              y={node.y + (node.size ?? 12) + 14}
              textAnchor="middle"
              fontSize={10}
              fill="var(--foreground, #333)"
            >
              {node.label}
            </text>
          </g>
        ))}
      </svg>

      {selected ? (
        <div className="absolute bottom-4 left-4 bg-card rounded-2xl card-shadow p-3.5 max-w-xs">
          <h4 className="text-sm font-semibold mb-1">{selected.label}</h4>
          <p className="text-xs text-muted-foreground">
            Mastery: {Math.round(selected.mastery * 100)}% · Level: {selected.level} ·
            Status: {selected.status}
          </p>
        </div>
      ) : null}
    </div>
  );
}
