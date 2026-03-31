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

export function collectContentNodes(nodes: ContentNode[]): ContentNode[] {
  const result: ContentNode[] = [];
  for (const node of nodes) {
    if (node.content?.trim()) result.push(node);
    if (node.children?.length) {
      result.push(...collectContentNodes(node.children));
    }
  }
  return result;
}

export function findPathToNode(nodes: ContentNode[], nodeId: string): ContentNode[] {
  const walk = (items: ContentNode[], trail: ContentNode[]): ContentNode[] | null => {
    for (const item of items) {
      const nextTrail = [...trail, item];
      if (item.id === nodeId) return nextTrail;
      if (item.children?.length) {
        const found = walk(item.children, nextTrail);
        if (found) return found;
      }
    }
    return null;
  };

  return walk(nodes, []) ?? [];
}

function collectTitles(node: ContentNode): string[] {
  const titles: string[] = [node.title];
  for (const child of node.children ?? []) {
    titles.push(...collectTitles(child));
  }
  return titles;
}

export function buildFocusTerms(node: ContentNode): string[] {
  const tokens = collectTitles(node)
    .flatMap((title) =>
      title
        .toLowerCase()
        .split(/[^a-z0-9\u4e00-\u9fa5]+/)
        .map((part) => part.trim())
        .filter((part) => part.length >= 2),
    )
    .filter((token, idx, arr) => arr.indexOf(token) === idx);

  return tokens.slice(0, 12);
}
