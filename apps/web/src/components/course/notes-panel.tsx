"use client";

import { useState, useRef, useCallback } from "react";
import { ChevronRight, ChevronDown, List } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { MarkdownRenderer } from "@/components/course/markdown-renderer";
import type { ContentNode } from "@/lib/api";

/**
 * Notes Panel — displays course content tree with:
 * - Collapsible chapter navigation sidebar (TOC)
 * - Mermaid/KaTeX markdown rendering
 * - AI restructure button (Phase 0-B)
 *
 * Reference: PageIndex content tree navigation pattern.
 */

interface NotesPanelProps {
  contentTree: ContentNode[];
}

// ── Chapter Navigation (TOC) ──

function TocItem({
  node,
  depth,
  activeId,
  onSelect,
}: {
  node: ContentNode;
  depth: number;
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(depth < 2);
  const hasChildren = node.children && node.children.length > 0;
  const isActive = activeId === node.id;

  return (
    <div>
      <button
        className={`flex items-center gap-1 w-full text-left px-2 py-1 text-xs rounded hover:bg-muted transition-colors ${
          isActive ? "bg-muted font-medium" : "text-muted-foreground"
        }`}
        style={{ paddingLeft: `${8 + depth * 12}px` }}
        onClick={() => {
          onSelect(node.id);
          if (hasChildren) setExpanded(!expanded);
        }}
      >
        {hasChildren ? (
          expanded ? (
            <ChevronDown className="h-3 w-3 shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0" />
          )
        ) : (
          <span className="w-3 shrink-0" />
        )}
        <span className="truncate">{node.title}</span>
      </button>
      {expanded && hasChildren && (
        <div>
          {node.children!.map((child) => (
            <TocItem
              key={child.id}
              node={child}
              depth={depth + 1}
              activeId={activeId}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Content Node Rendering ──

function ContentNodeItem({
  node,
  depth = 0,
}: {
  node: ContentNode;
  depth?: number;
}) {
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
      {headingLevel === 1 && <h1 className={headingClass}>{node.title}</h1>}
      {headingLevel === 2 && <h2 className={headingClass}>{node.title}</h2>}
      {headingLevel === 3 && <h3 className={headingClass}>{node.title}</h3>}
      {headingLevel === 4 && <h4 className={headingClass}>{node.title}</h4>}
      {headingLevel === 5 && <h5 className={headingClass}>{node.title}</h5>}
      {headingLevel >= 6 && <h6 className={headingClass}>{node.title}</h6>}
      {node.content && (
        <MarkdownRenderer
          content={node.content}
          className="text-sm leading-relaxed prose prose-sm max-w-none dark:prose-invert"
        />
      )}
      {node.children?.map((child) => (
        <ContentNodeItem key={child.id} node={child} depth={depth + 1} />
      ))}
    </div>
  );
}

// ── Main Panel ──

export function NotesPanel({ contentTree }: NotesPanelProps) {
  const [showToc, setShowToc] = useState(true);
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  const scrollToNode = useCallback((nodeId: string) => {
    setActiveNodeId(nodeId);
    const el = document.getElementById(`content-${nodeId}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, []);

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
    <div className="flex-1 flex overflow-hidden">
      {/* Chapter Navigation Sidebar (TOC) */}
      {showToc && (
        <div className="w-48 border-r shrink-0 flex flex-col">
          <div className="px-2 py-1.5 border-b flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Chapters</span>
          </div>
          <ScrollArea className="flex-1">
            <div className="py-1">
              {contentTree.map((node) => (
                <TocItem
                  key={node.id}
                  node={node}
                  depth={0}
                  activeId={activeNodeId}
                  onSelect={scrollToNode}
                />
              ))}
            </div>
          </ScrollArea>
        </div>
      )}

      {/* Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Toolbar */}
        <div className="px-3 py-1.5 border-b flex items-center gap-2 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2"
            onClick={() => setShowToc(!showToc)}
          >
            <List className="h-3 w-3 mr-1" />
            <span className="text-xs">{showToc ? "Hide" : "Show"} TOC</span>
          </Button>
        </div>

        <ScrollArea className="flex-1 p-4" ref={scrollAreaRef}>
          {contentTree.map((node) => (
            <ContentNodeItem key={node.id} node={node} />
          ))}
        </ScrollArea>
      </div>
    </div>
  );
}
