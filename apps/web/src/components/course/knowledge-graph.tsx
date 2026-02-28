"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Loader2, Maximize2, ZoomIn, ZoomOut } from "lucide-react";
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
 * Renders course content tree as a force-directed graph.
 */
export function KnowledgeGraph({ courseId }: KnowledgeGraphProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [zoom, setZoom] = useState(1);

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

  const layoutAndDraw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;

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

    // Clear
    ctx.clearRect(0, 0, width, height);
    ctx.save();
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
  }, [edges, nodes, zoom]);

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
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 text-center">
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
          >
            <ZoomIn className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => setZoom((z) => Math.max(z - 0.2, 0.3))}
          >
            <ZoomOut className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => setZoom(1)}
          >
            <Maximize2 className="h-3 w-3" />
          </Button>
        </div>
      </div>
      <div className="flex-1 relative">
        <canvas
          ref={canvasRef}
          width={800}
          height={600}
          className="w-full h-full"
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
