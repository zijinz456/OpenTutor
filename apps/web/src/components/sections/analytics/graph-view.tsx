"use client";

import { useCallback, useEffect, useState } from "react";
import { useT } from "@/lib/i18n-context";
import {
  getKnowledgeGraph,
  type KnowledgeGraphEdge,
} from "@/lib/api";
import {
  buildFocusedGraph,
  runSimulationStep,
  WIDTH,
  HEIGHT,
  MAX_ITER,
  type SimNode,
} from "./graph-simulation";

interface GraphViewProps {
  courseId: string;
  focusTerms?: string[];
  maxNodes?: number;
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
      const nextNodes = runSimulationStep(nodes, edges, nodeMap);
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
    <div role="region" aria-label="Knowledge graph" className="flex-1 flex flex-col overflow-hidden" data-testid="graph-panel">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full h-full min-h-0 bg-background"
        role="img"
        aria-label="Knowledge graph visualization"
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
