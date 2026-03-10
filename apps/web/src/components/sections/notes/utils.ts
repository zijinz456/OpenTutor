import type { ContentNode } from "@/lib/api";

export function findFirstContentNode(nodes: ContentNode[]): ContentNode | null {
  for (const node of nodes) {
    if (node.content?.trim()) return node;
    const child = findFirstContentNode(node.children ?? []);
    if (child) return child;
  }
  return null;
}

export function findNodeById(nodes: ContentNode[], nodeId: string | null): ContentNode | null {
  if (!nodeId) return null;
  for (const node of nodes) {
    if (node.id === nodeId) return node;
    const child = findNodeById(node.children ?? [], nodeId);
    if (child) return child;
  }
  return null;
}
