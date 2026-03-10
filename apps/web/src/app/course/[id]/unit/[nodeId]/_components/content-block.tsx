import type { ContentNode } from "@/lib/api";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";

export function ContentBlock({ node, depth = 0 }: { node: ContentNode; depth?: number }) {
  const headingLevel = Math.min((node.level ?? 0) + 1, 6);
  const sizeClass =
    headingLevel === 1 ? "text-2xl" :
    headingLevel === 2 ? "text-xl" :
    headingLevel === 3 ? "text-lg" : "text-base";

  return (
    <div className="mb-6" style={{ paddingLeft: depth > 0 ? `${depth * 12}px` : undefined }}>
      <h2 className={`font-semibold mb-3 ${sizeClass}`}>{node.title}</h2>
      {node.content ? (
        <MarkdownRenderer
          content={node.content}
          className="prose prose-sm max-w-none dark:prose-invert leading-relaxed"
        />
      ) : null}
      {node.children?.map((child) => (
        <ContentBlock key={child.id} node={child} depth={depth + 1} />
      ))}
    </div>
  );
}
