"use client";

import Link from "next/link";
import { Sparkles, ArrowRight } from "lucide-react";
import type { ContentNode } from "@/lib/api";

interface ContinueLearningCtaProps {
  courseId: string;
  nodes: ContentNode[];
}

function findFirstContentNode(nodes: ContentNode[]): ContentNode | null {
  for (const node of nodes) {
    if (node.content) return node;
    if (node.children?.length) {
      const found = findFirstContentNode(node.children);
      if (found) return found;
    }
  }
  return null;
}

export function ContinueLearningCta({ courseId, nodes }: ContinueLearningCtaProps) {
  const firstNode = findFirstContentNode(nodes);
  if (!firstNode) return null;

  return (
    <Link
      href={`/course/${courseId}/${firstNode.id}`}
      className="flex items-center gap-4 p-4 rounded-xl bg-primary/5 border border-primary/20 hover:bg-primary/10 transition-colors group"
    >
      <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 shrink-0">
        <Sparkles className="size-5 text-primary" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground">Continue Learning</p>
        <p className="text-xs text-muted-foreground truncate">{firstNode.title}</p>
      </div>
      <ArrowRight className="size-4 text-primary shrink-0 group-hover:translate-x-1 transition-transform" />
    </Link>
  );
}
