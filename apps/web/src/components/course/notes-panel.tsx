"use client";

import { ScrollArea } from "@/components/ui/scroll-area";
import type { ContentNode } from "@/lib/api";

/**
 * Notes Panel — displays course content tree as Markdown.
 *
 * Phase 0-A: Basic Markdown rendering of content tree.
 * Phase 0-B: AI-restructured notes with Mermaid/KaTeX rendering.
 */

interface NotesPanelProps {
  contentTree: ContentNode[];
}

function ContentNodeItem({ node, depth = 0 }: { node: ContentNode; depth?: number }) {
  const headingLevel = Math.min(node.level + 1, 6);

  const headingClass = `font-semibold mb-1 ${
    headingLevel === 1 ? "text-xl" :
    headingLevel === 2 ? "text-lg" :
    headingLevel === 3 ? "text-base" :
    "text-sm"
  }`;

  return (
    <div className="mb-4" style={{ paddingLeft: depth > 0 ? `${depth * 16}px` : undefined }}>
      {headingLevel === 1 && <h1 className={headingClass}>{node.title}</h1>}
      {headingLevel === 2 && <h2 className={headingClass}>{node.title}</h2>}
      {headingLevel === 3 && <h3 className={headingClass}>{node.title}</h3>}
      {headingLevel === 4 && <h4 className={headingClass}>{node.title}</h4>}
      {headingLevel === 5 && <h5 className={headingClass}>{node.title}</h5>}
      {headingLevel === 6 && <h6 className={headingClass}>{node.title}</h6>}
      {node.content && (
        <div className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed">
          {node.content}
        </div>
      )}
      {node.children?.map((child) => (
        <ContentNodeItem key={child.id} node={child} depth={depth + 1} />
      ))}
    </div>
  );
}

export function NotesPanel({ contentTree }: NotesPanelProps) {
  if (contentTree.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 text-center">
        <div>
          <p className="text-muted-foreground text-sm">No content yet</p>
          <p className="text-muted-foreground text-xs mt-1">
            Upload a PDF or paste a URL to see notes here
          </p>
        </div>
      </div>
    );
  }

  return (
    <ScrollArea className="flex-1 p-4">
      {contentTree.map((node) => (
        <ContentNodeItem key={node.id} node={node} />
      ))}
    </ScrollArea>
  );
}
