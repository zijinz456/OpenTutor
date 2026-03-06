"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useCourseStore } from "@/store/course";
import { useWorkspaceStore } from "@/store/workspace";
import { useT } from "@/lib/i18n-context";
import {
  listGeneratedNoteBatches,
  restructureNotes,
  saveGeneratedNotes,
  getAiNoteForNode,
  type ContentNode,
  type AiNoteForNode,
} from "@/lib/api";
import { useBatchManager } from "@/hooks/use-batch-manager";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { AiFeatureBlocked } from "@/components/shared/ai-feature-blocked";
import { toast } from "sonner";

interface NotesSectionProps {
  courseId: string;
  aiActionsEnabled?: boolean;
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

export function NotesSection({
  courseId,
  aiActionsEnabled = true,
}: NotesSectionProps) {
  const t = useT();
  const contentTree = useCourseStore((s) => s.contentTree);
  const fetchContentTree = useCourseStore((s) => s.fetchContentTree);
  const { saving, latestBatch, wrapSave } = useBatchManager({
    courseId,
    refreshSection: "notes",
    listFn: listGeneratedNoteBatches,
  });
  const selectedNodeId = useWorkspaceStore((s) => s.selectedNodeId);
  const setSelectedNodeId = useWorkspaceStore((s) => s.setSelectedNodeId);
  const [draft, setDraft] = useState<GeneratedNoteDraft | null>(null);
  const [generating, setGenerating] = useState(false);
  const [viewMode, setViewMode] = useState<"ai" | "source">("ai");
  const [aiNote, setAiNote] = useState<AiNoteForNode | null>(null);
  const [aiNoteLoading, setAiNoteLoading] = useState(false);

  const selectedNode = useMemo(
    () => findNodeById(contentTree, selectedNodeId) ?? findFirstContentNode(contentTree),
    [selectedNodeId, contentTree],
  );

  useEffect(() => {
    if (contentTree.length === 0) {
      void fetchContentTree(courseId);
    }
  }, [courseId, contentTree.length, fetchContentTree]);

  // Auto-select first content node if nothing is selected
  useEffect(() => {
    const firstNode = findFirstContentNode(contentTree);
    if (!firstNode) {
      if (selectedNodeId) setSelectedNodeId(null);
      if (draft) setDraft(null);
      return;
    }

    if (!selectedNodeId || !findNodeById(contentTree, selectedNodeId)) {
      setSelectedNodeId(firstNode.id);
    }
    if (draft && draft.sourceNodeId !== (selectedNode?.id ?? "")) {
      setDraft(null);
    }
  }, [contentTree, selectedNodeId, setSelectedNodeId, draft, selectedNode?.id]);

  // Fetch AI note for selected node
  useEffect(() => {
    if (!selectedNode) {
      setAiNote(null);
      return;
    }
    let cancelled = false;
    setAiNoteLoading(true);
    getAiNoteForNode(courseId, selectedNode.id)
      .then((note) => {
        if (!cancelled) {
          setAiNote(note);
          setAiNoteLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAiNote(null);
          setAiNoteLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [courseId, selectedNode?.id]);

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
      setViewMode("ai");
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

  // Determine what AI content to show
  const aiContent = draft?.markdown ?? aiNote?.markdown;
  const aiTitle = draft?.title ?? aiNote?.title;
  const hasAiNotes = !!(aiContent && aiContent.length > 0);

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
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-3 py-1.5 border-b flex items-center gap-2 shrink-0">
          {/* AI / Source toggle */}
          <div className="flex items-center gap-0.5 rounded-md border p-0.5">
            <button
              className={`px-2 py-0.5 text-xs rounded ${
                viewMode === "ai"
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setViewMode("ai")}
            >
              AI Notes
            </button>
            <button
              className={`px-2 py-0.5 text-xs rounded ${
                viewMode === "source"
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setViewMode("source")}
            >
              Source
            </button>
          </div>

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
              disabled={!aiActionsEnabled || generating || saving || !selectedNode}
            >
              {generating ? <span className="animate-pulse mr-1">...</span> : null}
              {t("notes.regenerate")}
            </Button>
          </div>
        </div>

        {!aiActionsEnabled ? <AiFeatureBlocked compact className="mx-4 mt-4" /> : null}

        <ScrollArea className="flex-1 p-4">
          {viewMode === "ai" ? (
            <>
              {aiNoteLoading ? (
                <div className="flex items-center justify-center py-12">
                  <p className="text-sm text-muted-foreground animate-pulse">Loading AI notes...</p>
                </div>
              ) : hasAiNotes ? (
                <div className="rounded-lg border bg-muted/20 p-4" data-testid="notes-preview">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium">{aiTitle}</p>
                      <p className="text-xs text-muted-foreground">
                        {draft ? "AI note preview" : "Auto-generated AI notes"}
                        {aiNote?.auto_generated ? " • auto" : ""}
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
                    content={aiContent!}
                    className="prose prose-sm max-w-none dark:prose-invert"
                  />
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-12 gap-3">
                  <p className="text-sm text-muted-foreground">
                    No AI notes yet for this section.
                  </p>
                  <Button
                    size="sm"
                    onClick={() => void handleGenerate()}
                    disabled={!aiActionsEnabled || generating || !selectedNode}
                  >
                    {generating ? "Generating..." : "Generate AI Notes"}
                  </Button>
                </div>
              )}
            </>
          ) : (
            // Source view: show selected node's content, or full tree
            selectedNode ? (
              <ContentNodeItem node={selectedNode} />
            ) : (
              contentTree.map((node) => (
                <ContentNodeItem key={node.id} node={node} />
              ))
            )
          )}
        </ScrollArea>
      </div>
    </div>
  );
}
