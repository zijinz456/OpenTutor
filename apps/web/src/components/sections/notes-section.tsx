"use client";

import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useCourseStore } from "@/store/course";
import { useT } from "@/lib/i18n-context";
import {
  listGeneratedNoteBatches,
  restructureNotes,
  saveGeneratedNotes,
  type ContentNode,
} from "@/lib/api";
import { useBatchManager } from "@/hooks/use-batch-manager";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { toast } from "sonner";

interface NotesSectionProps {
  courseId: string;
}

interface GeneratedNoteDraft {
  title: string;
  markdown: string;
  format: string;
  sourceNodeId: string;
}

function findFirstContentNode(nodes: ContentNode[]): ContentNode | null {
  for (const node of nodes) {
    if (node.content?.trim()) return node;
    const child = findFirstContentNode(node.children ?? []);
    if (child) return child;
  }
  return null;
}

function findNodeById(nodes: ContentNode[], nodeId: string | null): ContentNode | null {
  if (!nodeId) return null;
  for (const node of nodes) {
    if (node.id === nodeId) return node;
    const child = findNodeById(node.children ?? [], nodeId);
    if (child) return child;
  }
  return null;
}

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
  const hasChildren = !!node.children?.length;
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
          if (hasChildren) setExpanded((value) => !value);
        }}
      >
        {hasChildren ? (
          <span className="w-3 shrink-0 text-[10px] leading-none">
            {expanded ? "▼" : "▶"}
          </span>
        ) : (
          <span className="w-3 shrink-0" />
        )}
        <span className="truncate">{node.title}</span>
      </button>
      {expanded && hasChildren ? (
        <div>
          {node.children?.map((child) => (
            <TocItem
              key={child.id}
              node={child}
              depth={depth + 1}
              activeId={activeId}
              onSelect={onSelect}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

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

export function NotesSection({ courseId }: NotesSectionProps) {
  const t = useT();
  const contentTree = useCourseStore((s) => s.contentTree);
  const fetchContentTree = useCourseStore((s) => s.fetchContentTree);
  const { saving, latestBatch, wrapSave } = useBatchManager({
    courseId,
    refreshSection: "notes",
    listFn: listGeneratedNoteBatches,
  });
  const [showToc, setShowToc] = useState(true);
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null);
  const [draft, setDraft] = useState<GeneratedNoteDraft | null>(null);
  const [generating, setGenerating] = useState(false);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  const scrollToNode = useCallback((nodeId: string) => {
    setActiveNodeId(nodeId);
    setDraft((current) => (
      current && current.sourceNodeId === nodeId ? current : null
    ));
    const el = document.getElementById(`content-${nodeId}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, []);

  const selectedNode = useMemo(
    () => findNodeById(contentTree, activeNodeId) ?? findFirstContentNode(contentTree),
    [activeNodeId, contentTree],
  );

  useEffect(() => {
    if (contentTree.length === 0) {
      void fetchContentTree(courseId);
    }
  }, [courseId, contentTree.length, fetchContentTree]);

  useEffect(() => {
    const firstNode = findFirstContentNode(contentTree);
    if (!firstNode) {
      if (activeNodeId) setActiveNodeId(null);
      if (draft) setDraft(null);
      return;
    }

    const resolvedNode = findNodeById(contentTree, activeNodeId) ?? firstNode;
    if (resolvedNode.id !== activeNodeId) {
      setActiveNodeId(resolvedNode.id);
    }
    if (draft && draft.sourceNodeId !== resolvedNode.id) {
      setDraft(null);
    }
  }, [activeNodeId, contentTree, draft]);

  const handleGenerate = useCallback(async () => {
    if (!selectedNode) {
      toast.error("Select a section with content first");
      return;
    }

    setGenerating(true);
    try {
      const result = await restructureNotes(selectedNode.id);
      setDraft({
        title: result.original_title,
        markdown: result.ai_content,
        format: result.format_used,
        sourceNodeId: selectedNode.id,
      });
      toast.success("Generated AI notes");
    } catch (error) {
      toast.error((error as Error).message || "Failed to generate notes");
    } finally {
      setGenerating(false);
    }
  }, [selectedNode]);

  const handleSave = useCallback(
    async (replaceBatchId?: string) => {
      if (!draft) return;
      await wrapSave(() =>
        saveGeneratedNotes(courseId, draft.markdown, draft.title, draft.sourceNodeId, replaceBatchId),
      );
    },
    [courseId, draft, wrapSave],
  );

  if (contentTree.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 text-center">
        <div>
          <p className="text-muted-foreground text-sm">{t("notes.empty")}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex overflow-hidden" data-testid="notes-panel">
      {showToc ? (
        <div className="w-48 border-r shrink-0 flex flex-col">
          <div className="px-2 py-1.5 border-b flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">
              {t("notes.toc")}
            </span>
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
      ) : null}

      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-3 py-1.5 border-b flex items-center gap-2 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2"
            onClick={() => setShowToc((value) => !value)}
          >
            <span className="text-xs">{showToc ? "Hide" : "Show"} TOC</span>
          </Button>
          <div className="ml-auto flex items-center gap-2">
            {selectedNode ? (
              <Badge variant="outline" className="max-w-56 truncate">
                {selectedNode.title}
              </Badge>
            ) : null}
            {draft && latestBatch?.is_active ? (
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2 text-xs"
                onClick={() => void handleSave(latestBatch.batch_id)}
                disabled={saving || generating}
              >
                Replace Latest
              </Button>
            ) : null}
            {draft ? (
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2 text-xs"
                onClick={() => void handleSave()}
                disabled={saving || generating}
              >
                Save New
              </Button>
            ) : null}
            <Button
              data-testid="notes-generate"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => void handleGenerate()}
              disabled={generating || saving || !selectedNode}
            >
              {generating ? <span className="animate-pulse mr-1">...</span> : null}
              {t("notes.regenerate")}
            </Button>
          </div>
        </div>

        <ScrollArea className="flex-1 p-4" ref={scrollAreaRef}>
          {draft ? (
            <div className="mb-6 rounded-lg border bg-muted/20 p-4" data-testid="notes-preview">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">{draft.title}</p>
                  <p className="text-xs text-muted-foreground">
                    AI note preview • {draft.format}
                  </p>
                </div>
                {latestBatch ? (
                  <Badge variant="secondary">
                    v{latestBatch.current_version}
                    {latestBatch.is_active ? " active" : ""}
                  </Badge>
                ) : null}
              </div>
              <MarkdownRenderer
                content={draft.markdown}
                className="prose prose-sm max-w-none dark:prose-invert"
              />
            </div>
          ) : null}

          {contentTree.map((node) => (
            <ContentNodeItem key={node.id} node={node} />
          ))}
        </ScrollArea>
      </div>
    </div>
  );
}
