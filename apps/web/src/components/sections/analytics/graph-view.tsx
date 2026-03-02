"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useT } from "@/lib/i18n-context";
import {
  getKnowledgeGraph,
  type KnowledgeGraphNode,
  type KnowledgeGraphEdge,
} from "@/lib/api";

interface GraphViewProps {
  courseId: string;
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

export function GraphView({ courseId }: GraphViewProps) {
  const t = useT();
  const svgRef = useRef<SVGSVGElement>(null);
  const [nodes, setNodes] = useState<SimNode[]>([]);
  const [edges, setEdges] = useState<KnowledgeGraphEdge[]>([]);
  const [selected, setSelected] = useState<SimNode | null>(null);
  const [loading, setLoading] = useState(true);
  const [empty, setEmpty] = useState(false);

  /* Fetch data */
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getKnowledgeGraph(courseId)
      .then((data) => {
        if (cancelled) return;
        if (!data.nodes?.length) {
          setEmpty(true);
          setLoading(false);
          return;
        }
        /* Initialize positions in a circle */
        const cx = WIDTH / 2;
        const cy = HEIGHT / 2;
        const r = Math.min(WIDTH, HEIGHT) * 0.35;
        const simNodes: SimNode[] = data.nodes.map((n, i) => {
          const angle = (2 * Math.PI * i) / data.nodes.length;
          return {
            ...n,
            x: cx + r * Math.cos(angle),
            y: cy + r * Math.sin(angle),
            vx: 0,
            vy: 0,
          };
        });
        setEdges(data.edges ?? []);
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
  }, [courseId]);

  /* Force simulation */
  useEffect(() => {
    if (nodes.length === 0) return;
    let iter = 0;
    let frame: number;
    const nodeMap = new Map<string, number>();
    nodes.forEach((n, i) => nodeMap.set(n.id, i));

    const step = () => {
      if (iter >= MAX_ITER) return;
      iter++;
      const ns = nodes;

      /* Repulsion between all pairs */
      for (let i = 0; i < ns.length; i++) {
        for (let j = i + 1; j < ns.length; j++) {
          let dx = ns[i].x - ns[j].x;
          let dy = ns[i].y - ns[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = REPULSION / (dist * dist);
          dx = (dx / dist) * force;
          dy = (dy / dist) * force;
          ns[i].vx += dx;
          ns[i].vy += dy;
          ns[j].vx -= dx;
          ns[j].vy -= dy;
        }
      }

      /* Spring attraction along edges */
      for (const e of edges) {
        const si = nodeMap.get(e.source);
        const ti = nodeMap.get(e.target);
        if (si === undefined || ti === undefined) continue;
        const dx = ns[ti].x - ns[si].x;
        const dy = ns[ti].y - ns[si].y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const displacement = dist - SPRING_LEN;
        const fx = SPRING_K * displacement * (dx / dist);
        const fy = SPRING_K * displacement * (dy / dist);
        ns[si].vx += fx;
        ns[si].vy += fy;
        ns[ti].vx -= fx;
        ns[ti].vy -= fy;
      }

      /* Apply velocity + damping, clamp to bounds */
      for (const n of ns) {
        n.vx *= DAMPING;
        n.vy *= DAMPING;
        n.x += n.vx;
        n.y += n.vy;
        n.x = Math.max(30, Math.min(WIDTH - 30, n.x));
        n.y = Math.max(30, Math.min(HEIGHT - 30, n.y));
      }

      setNodes([...ns]);
      frame = requestAnimationFrame(step);
    };

    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
    // Run simulation once when nodes first populate
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes.length, edges]);

  const handleNodeClick = useCallback(
    (node: SimNode) => {
      setSelected(selected?.id === node.id ? null : node);
    },
    [selected],
  );

  /* Empty / loading states */
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <p className="text-xs text-muted-foreground">Loading graph...</p>
      </div>
    );
  }

  if (empty) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <h3 className="text-sm font-medium mb-1">{t("course.graph")}</h3>
        <p className="text-xs text-muted-foreground max-w-xs">
          Knowledge graph visualization will appear here.
        </p>
      </div>
    );
  }

  const nodeById = new Map(nodes.map((n) => [n.id, n]));

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full h-full min-h-0 bg-background"
      >
        {/* Edges */}
        {edges.map((e) => {
          const s = nodeById.get(e.source);
          const tgt = nodeById.get(e.target);
          if (!s || !tgt) return null;
          return (
            <line
              key={`${e.source}-${e.target}`}
              x1={s.x}
              y1={s.y}
              x2={tgt.x}
              y2={tgt.y}
              stroke="var(--border, #ccc)"
              strokeWidth={1.5}
              strokeOpacity={0.5}
            />
          );
        })}
        {/* Nodes */}
        {nodes.map((n) => (
          <g
            key={n.id}
            onClick={() => handleNodeClick(n)}
            className="cursor-pointer"
          >
            <circle
              cx={n.x}
              cy={n.y}
              r={Math.max(8, n.size ?? 12)}
              fill={n.color}
              stroke={selected?.id === n.id ? "#fff" : "none"}
              strokeWidth={selected?.id === n.id ? 3 : 0}
              opacity={0.9}
            />
            <text
              x={n.x}
              y={n.y + (n.size ?? 12) + 14}
              textAnchor="middle"
              fontSize={10}
              fill="var(--foreground, #333)"
            >
              {n.label}
            </text>
          </g>
        ))}
      </svg>

      {/* Selected node details */}
      {selected && (
        <div className="absolute bottom-4 left-4 bg-card border rounded-lg shadow-lg p-3 max-w-xs">
          <h4 className="text-sm font-semibold mb-1">{selected.label}</h4>
          <p className="text-xs text-muted-foreground">
            Mastery: {Math.round(selected.mastery * 100)}% &middot; Level:{" "}
            {selected.level} &middot; Status: {selected.status}
          </p>
        </div>
      )}
    </div>
  );
}
