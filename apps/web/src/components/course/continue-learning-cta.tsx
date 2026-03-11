"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Sparkles, ArrowRight, PlayCircle } from "lucide-react";
import type { ContentNode } from "@/lib/api";

interface ContinueLearningCtaProps {
  courseId: string;
  nodes: ContentNode[];
}

function collectAllContentNodes(nodes: ContentNode[]): ContentNode[] {
  const result: ContentNode[] = [];
  for (const node of nodes) {
    if (node.content?.trim()) result.push(node);
    if (node.children?.length) result.push(...collectAllContentNodes(node.children));
  }
  return result;
}

export function ContinueLearningCta({ courseId, nodes }: ContinueLearningCtaProps) {
  const { targetNode, isResume } = useMemo(() => {
    const allNodes = collectAllContentNodes(nodes);
    if (allNodes.length === 0) return { targetNode: null, isResume: false };

    // Check localStorage for last visited node
    try {
      const lastNodeId = localStorage.getItem(`opentutor_last_node_${courseId}`);
      if (lastNodeId) {
        const lastIndex = allNodes.findIndex((n) => n.id === lastNodeId);
        if (lastIndex >= 0) {
          // Link to the next node after the last visited, or the last one itself if at end
          const nextIndex = Math.min(lastIndex + 1, allNodes.length - 1);
          return { targetNode: allNodes[nextIndex], isResume: true };
        }
      }
    } catch {}

    return { targetNode: allNodes[0], isResume: false };
  }, [nodes, courseId]);

  if (!targetNode) return null;

  return (
    <Link
      href={`/course/${courseId}/unit/${targetNode.id}`}
      aria-label={`${isResume ? "Continue" : "Start"} learning: ${targetNode.title}`}
      className="flex items-center gap-4 p-4 rounded-2xl bg-primary/5 border border-primary/20 hover:bg-primary/10 transition-colors group card-lift"
    >
      <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-primary/10 shrink-0">
        {isResume ? <PlayCircle className="size-5 text-primary" /> : <Sparkles className="size-5 text-primary" />}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground">
          {isResume ? "Continue Learning" : "Start Learning"}
        </p>
        <p className="text-xs text-muted-foreground truncate">{targetNode.title}</p>
      </div>
      <ArrowRight className="size-4 text-primary shrink-0 group-hover:translate-x-1 transition-transform" />
    </Link>
  );
}
