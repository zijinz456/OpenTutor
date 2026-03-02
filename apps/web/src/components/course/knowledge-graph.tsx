"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import {
  getKnowledgeGraph,
  type KnowledgeGraphNode as GraphNode,
  type KnowledgeGraphEdge as GraphEdge,
} from "@/lib/api";

interface KnowledgeGraphProps {
  courseId: string;
}

/**
 * Knowledge graph visualization using Canvas API.
 * Renders course content tree as a hierarchical circular graph.
 * Uses ResizeObserver + devicePixelRatio for crisp rendering at any size.
 */
export function KnowledgeGraph({ courseId }: KnowledgeGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [zoom, setZoom] = useState(1);
  const [canvasSize, setCanvasSize] = useState({ width: 800, height: 600 });

  const loadGraph = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getKnowledgeGraph(courseId);
      setNodes(data.nodes || []);
      setEdges(data.edges || []);
    } catch {
      // Expected when no content exists
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  // Resize canvas to match container with DPR-aware backing store
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setCanvasSize({ width: Math.round(width), height: Math.round(height) });
        }
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // Apply DPR scaling to canvas backing store
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvasSize.width * dpr;
    canvas.height = canvasSize.height * dpr;
    canvas.style.width = `${canvasSize.width}px`;
    canvas.style.height = `${canvasSize.height}px`;
    const ctx = canvas.getContext("2d");
    if (ctx) ctx.scale(dpr, dpr);
  }, [canvasSize]);

  const layoutAndDraw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const width = canvasSize.width;
    const height = canvasSize.height;

    // Simple hierarchical layout
    const layoutNodes = [...nodes];
    const levels = new Map<number, GraphNode[]>();

    for (const node of layoutNodes) {
      if (!levels.has(node.level)) levels.set(node.level, []);
      levels.get(node.level)!.push(node);
    }

    const maxLevel = Math.max(...levels.keys(), 0);
    const centerX = width / 2;
    const centerY = height / 2;

    for (const [level, levelNodes] of levels.entries()) {
      const radius = (level + 1) * Math.min(width, height) / (maxLevel + 2) / 2;
      const angleStep = (2 * Math.PI) / Math.max(levelNodes.length, 1);

      levelNodes.forEach((node, i) => {
        const angle = i * angleStep - Math.PI / 2;
        node.x = centerX + radius * Math.cos(angle);
        node.y = centerY + radius * Math.sin(angle);
      });
    }

    // Build node map for edge rendering
    const nodeMap = new Map(layoutNodes.map((n) => [n.id, n]));

    // Clear (use backing store size to clear everything)
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.restore();

    ctx.save();
    const dprScale = dpr;
    ctx.setTransform(dprScale, 0, 0, dprScale, 0, 0);
    ctx.translate(width / 2 * (1 - zoom), height / 2 * (1 - zoom));
    ctx.scale(zoom, zoom);

    // Draw edges
    ctx.strokeStyle = "#e5e7eb";
    ctx.lineWidth = 1;
    for (const edge of edges) {
      const source = nodeMap.get(edge.source);
      const target = nodeMap.get(edge.target);
      if (source?.x != null && target?.x != null) {
        ctx.beginPath();
        ctx.moveTo(source.x, source.y!);
        ctx.lineTo(target.x, target.y!);
        ctx.stroke();
      }
    }

    // Draw nodes
    for (const node of layoutNodes) {
      if (node.x == null || node.y == null) continue;

      ctx.beginPath();
      ctx.arc(node.x, node.y, node.size, 0, 2 * Math.PI);
      ctx.fillStyle = node.color;
      ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.stroke();

      // Label
      ctx.fillStyle = "#374151";
      ctx.font = `${Math.max(9, 12 - node.level)}px system-ui`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      const label =
        node.label.length > 20 ? node.label.slice(0, 18) + "..." : node.label;
      ctx.fillText(label, node.x, node.y + node.size + 3);
    }

    ctx.restore();
  }, [edges, nodes, zoom, canvasSize]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  useEffect(() => {
    if (nodes.length > 0) {
      layoutAndDraw();
    }
  }, [layoutAndDraw, nodes.length]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center" data-testid="graph-panel">
        <span className="text-sm animate-pulse text-muted-foreground">Loading...</span>
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 text-center" data-testid="graph-panel">
        <p className="text-muted-foreground text-sm">
          Upload course materials to generate the knowledge graph
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col">
      <div className="px-3 py-1 border-b flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {nodes.length} topics, {edges.length} connections
        </span>
        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => setZoom((z) => Math.min(z + 0.2, 3))}
            title="Zoom in"
          >
            <span className="text-xs font-bold">+</span>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => setZoom((z) => Math.max(z - 0.2, 0.3))}
            title="Zoom out"
          >
            <span className="text-xs font-bold">{"\u2212"}</span>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => setZoom(1)}
            title="Reset zoom"
          >
            <span className="text-[10px] font-medium">1:1</span>
          </Button>
        </div>
      </div>
      <div ref={containerRef} className="flex-1 relative">
        <canvas
          ref={canvasRef}
          className="absolute inset-0"
        />
        {/* Legend */}
        <div className="absolute bottom-2 left-2 bg-background/80 backdrop-blur-sm rounded p-2 text-xs flex gap-3">
          <LegendItem color="#22c55e" label="Mastered" />
          <LegendItem color="#3b82f6" label="Reviewed" />
          <LegendItem color="#eab308" label="In Progress" />
          <LegendItem color="#9ca3af" label="Not Started" />
        </div>
      </div>
    </div>
  );
}

function LegendItem({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1">
      <div className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
      <span>{label}</span>
    </div>
  );
}
