"use client";

import { useState, useCallback, useEffect, useMemo, useRef } from "react";
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
  type AiNoteForNode,
} from "@/lib/api";
import { stabilizeMarkdownMermaidBlocks } from "@/lib/markdown/mermaid";
import { useBatchManager } from "@/hooks/use-batch-manager";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { AiFeatureBlocked } from "@/components/shared/ai-feature-blocked";
import { collectContentNodes, findFirstContentNode, findNodeById } from "@/lib/content-tree";
import { ContentNodeItem } from "./notes/content-node-item";
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

function cleanNoteText(value: unknown): string {
  return typeof value === "string" ? value.replaceAll("\u0000", "").trim() : "";
}

function cleanNoteMarkdown(value: unknown): string {
  const markdown = cleanNoteText(value);
  return markdown ? stabilizeMarkdownMermaidBlocks(markdown) : "";
}

function normalizeGeneratedNoteDraft(
  payload: unknown,
  sourceNodeId: string,
  fallbackTitle: string,
): GeneratedNoteDraft | null {
  if (!payload || typeof payload !== "object") return null;

  const record = payload as Record<string, unknown>;
  const markdown = cleanNoteMarkdown(record.ai_content);
  if (!markdown) return null;

  return {
    title: cleanNoteText(record.original_title) || fallbackTitle,
    markdown,
    format: cleanNoteText(record.format_used) || "markdown",
    sourceNodeId,
  };
}

function normalizeAiNote(note: AiNoteForNode | null): AiNoteForNode | null {
  if (!note || typeof note !== "object") return null;

  const markdown = cleanNoteMarkdown(note.markdown);
  if (!markdown) return null;

  return {
    id: typeof note.id === "string" ? note.id : "",
    title: cleanNoteText(note.title) || "AI Notes",
    markdown,
    format: cleanNoteText(note.format) || "markdown",
    auto_generated: !!note.auto_generated,
    version: typeof note.version === "number" ? note.version : 1,
  };
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
  const aiFetchRequestRef = useRef(0);
  const generateRequestRef = useRef(0);

  const contentNodes = useMemo(() => collectContentNodes(contentTree), [contentTree]);

  const selectedNode = useMemo(
    () => findNodeById(contentTree, selectedNodeId) ?? findFirstContentNode(contentTree),
    [selectedNodeId, contentTree],
  );
  const selectedNodeForFetch = selectedNode?.id;

  const currentIndex = useMemo(
    () => contentNodes.findIndex((n) => n.id === selectedNode?.id),
    [contentNodes, selectedNode?.id],
  );
  const canPrev = currentIndex > 0;
  const canNext = currentIndex >= 0 && currentIndex < contentNodes.length - 1;

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
    if (!selectedNodeForFetch) {
      aiFetchRequestRef.current += 1;
      setAiNote(null);
      setAiNoteLoading(false);
      return;
    }

    const requestId = ++aiFetchRequestRef.current;
    let cancelled = false;
    setAiNoteLoading(true);
    getAiNoteForNode(courseId, selectedNodeForFetch)
      .then((note) => {
        if (!cancelled && requestId === aiFetchRequestRef.current) {
          setAiNote(normalizeAiNote(note));
          setAiNoteLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled && requestId === aiFetchRequestRef.current) {
          setAiNote(null);
          setAiNoteLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [courseId, selectedNodeForFetch]);

  const handleGenerate = useCallback(async () => {
    if (!selectedNode) {
      toast.error("Select a section with content first");
      return;
    }

    const requestId = ++generateRequestRef.current;
    setGenerating(true);
    try {
      const result = await restructureNotes(selectedNode.id);
      if (requestId !== generateRequestRef.current) return;

      const nextDraft = normalizeGeneratedNoteDraft(
        result,
        selectedNode.id,
        selectedNode.title || "Untitled section",
      );

      if (!nextDraft) {
        throw new Error("AI notes came back empty");
      }

      setDraft(nextDraft);
      setViewMode("ai");
      toast.success("Generated AI notes");
    } catch (error) {
      if (requestId === generateRequestRef.current) {
        toast.error((error as Error).message || "Failed to generate notes");
      }
    } finally {
      if (requestId === generateRequestRef.current) {
        setGenerating(false);
      }
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
    <div role="region" aria-label="Course notes" className="flex-1 flex overflow-hidden" data-testid="notes-panel">
      <div className="flex-1 flex flex-col overflow-hidden">
        <div role="toolbar" aria-label="Notes toolbar" className="px-3 py-1.5 border-b border-border/60 flex items-center gap-2 shrink-0">
          {/* AI / Source toggle */}
          <div role="group" aria-label="View mode" className="flex items-center gap-0.5 rounded-xl bg-muted/30 p-0.5">
            <button
              aria-pressed={viewMode === "ai" ? "true" : "false"}
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
              aria-pressed={viewMode === "source" ? "true" : "false"}
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
            {/* Node selector: prev / dropdown / next */}
            {contentNodes.length > 1 && (
              <>
                <button
                  type="button"
                  className="px-1 py-0.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-30"
                  disabled={!canPrev}
                  onClick={() => canPrev && setSelectedNodeId(contentNodes[currentIndex - 1].id)}
                  aria-label="Previous section"
                >
                  &lsaquo;
                </button>
                <select
                  value={selectedNode?.id ?? ""}
                  onChange={(e) => setSelectedNodeId(e.target.value)}
                  className="h-6 text-xs rounded border border-border bg-background px-1 max-w-[160px] truncate"
                  aria-label="Select section"
                >
                  {contentNodes.map((n, i) => (
                    <option key={n.id} value={n.id}>
                      {n.title || `Section ${i + 1}`}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="px-1 py-0.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-30"
                  disabled={!canNext}
                  onClick={() => canNext && setSelectedNodeId(contentNodes[currentIndex + 1].id)}
                  aria-label="Next section"
                >
                  &rsaquo;
                </button>
              </>
            )}
            {contentNodes.length <= 1 && selectedNode ? (
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

        <ScrollArea className="flex-1 p-4 scrollbar-thin">
          {viewMode === "ai" ? (
            <>
              {aiNoteLoading ? (
                <div className="flex items-center justify-center py-12">
                  <p className="text-sm text-muted-foreground animate-pulse">Loading AI notes...</p>
                </div>
              ) : hasAiNotes ? (
                <div className="rounded-2xl card-shadow bg-muted/20 p-4" data-testid="notes-preview">
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
