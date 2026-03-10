"use client";

import type { ContentNode } from "@/lib/api";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";

interface ContentNodeItemProps {
  node: ContentNode;
  depth?: number;
}

export function ContentNodeItem({ node, depth = 0 }: ContentNodeItemProps) {
  const headingLevel = Math.min(node.level + 1, 6);

  const headingClass = `font-semibold mb-1 ${
    headingLevel === 1
      ? "text-xl"
      : headingLevel === 2
        ? "text-lg"
        : headingLevel === 3
          ? "text-base"
          : "text-sm"
  }`;

  return (
    <div
      id={`content-${node.id}`}
      className="mb-4"
      style={{ paddingLeft: depth > 0 ? `${depth * 16}px` : undefined }}
    >
      {(() => {
        const Tag = `h${headingLevel}` as keyof React.JSX.IntrinsicElements;
        return <Tag className={headingClass}>{node.title}</Tag>;
      })()}
      {node.content ? (
        <MarkdownRenderer
          content={node.content}
          className="text-sm leading-relaxed prose prose-sm max-w-none dark:prose-invert"
        />
      ) : null}
      {node.children?.map((child) => (
        <ContentNodeItem key={child.id} node={child} depth={depth + 1} />
      ))}
    </div>
  );
}
