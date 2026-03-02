"use client";

import { useEffect, useMemo, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { useCourseStore } from "@/store/course";
import { useT } from "@/lib/i18n-context";
import {
  listGeneratedNoteBatches,
  restructureNotes,
  saveGeneratedNotes,
  type ContentNode,
  type GeneratedAssetBatchSummary,
  type RestructuredNotes,
} from "@/lib/api";
import { ChevronRight, ChevronDown, FileText, Sparkles } from "lucide-react";

interface NotesSectionProps {
  courseId: string;
}

function findNode(nodes: ContentNode[], nodeId: string | null): ContentNode | null {
  if (!nodeId) return null;
  for (const node of nodes) {
    if (node.id === nodeId) return node;
    const child = findNode(node.children ?? [], nodeId);
    if (child) return child;
  }
  return null;
}

function extractBatchMarkdown(batch: GeneratedAssetBatchSummary | null): string {
  const preview = batch?.preview as { markdown?: unknown } | undefined;
  return typeof preview?.markdown === "string" ? preview.markdown : "";
}

function ContentTreeNode({
  node,
  depth,
  selectedId,
  onSelect,
}: {
  node: ContentNode;
  depth: number;
  selectedId: string | null;
  onSelect: (node: ContentNode) => void;
}) {
  const [expanded, setExpanded] = useState(depth < 1);
  const hasChildren = node.children && node.children.length > 0;
  const isSelected = selectedId === node.id;

  return (
    <div>
      <button
        type="button"
        className={`flex items-center gap-1.5 w-full text-left px-3 py-2 text-sm rounded-md transition-colors ${
          isSelected ? "bg-primary/10 text-foreground" : "hover:bg-muted/60"
        }`}
        style={{ paddingLeft: `${12 + depth * 16}px` }}
        onClick={() => {
          if (hasChildren) setExpanded((value) => !value);
          onSelect(node);
        }}
      >
        {hasChildren ? (
          expanded ? (
            <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
          )
        ) : (
          <FileText className="size-3.5 shrink-0 text-muted-foreground/50" />
        )}
        <span className="truncate font-medium">{node.title}</span>
      </button>

      {expanded && hasChildren && (
        <div>
          {node.children.map((child) => (
            <ContentTreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function NotesSection({ courseId }: NotesSectionProps) {
  const t = useT();
  const contentTree = useCourseStore((s) => s.contentTree);
  const fetchContentTree = useCourseStore((s) => s.fetchContentTree);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [savedBatches, setSavedBatches] = useState<GeneratedAssetBatchSummary[]>([]);
  const [generatedNotes, setGeneratedNotes] = useState<RestructuredNotes | null>(null);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (contentTree.length === 0) {
      void fetchContentTree(courseId);
    }
  }, [courseId, contentTree.length, fetchContentTree]);

  useEffect(() => {
    if (selectedNodeId || contentTree.length === 0) return;

    const stack = [...contentTree];
    while (stack.length > 0) {
      const node = stack.shift();
      if (!node) continue;
      if (node.content) {
        setSelectedNodeId(node.id);
        return;
      }
      stack.unshift(...(node.children ?? []));
    }
  }, [contentTree, selectedNodeId]);

  useEffect(() => {
    let cancelled = false;

    const loadSaved = async () => {
      setLoadingSaved(true);
      try {
        const data = await listGeneratedNoteBatches(courseId);
        if (!cancelled) setSavedBatches(data);
      } catch {
        if (!cancelled) setSavedBatches([]);
      } finally {
        if (!cancelled) setLoadingSaved(false);
      }
    };

    void loadSaved();
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  const selectedNode = useMemo(
    () => findNode(contentTree, selectedNodeId),
    [contentTree, selectedNodeId],
  );

  const latestSavedBatch = savedBatches[0] ?? null;
  const previewContent = generatedNotes?.ai_content
    || extractBatchMarkdown(latestSavedBatch)
    || selectedNode?.content
    || "";

  const handleGenerate = async () => {
    if (!selectedNode?.content) return;
    setGenerating(true);
    setMessage(null);
    setError(null);
    try {
      const result = await restructureNotes(selectedNode.id);
      setGeneratedNotes(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate notes");
    } finally {
      setGenerating(false);
    }
  };

  const handleSave = async () => {
    if (!generatedNotes?.ai_content) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      await saveGeneratedNotes(
        courseId,
        generatedNotes.ai_content,
        selectedNode?.title || generatedNotes.original_title,
        selectedNode?.id,
        latestSavedBatch?.batch_id,
      );
      setMessage("Generated notes saved.");
      const refreshed = await listGeneratedNoteBatches(courseId);
      setSavedBatches(refreshed);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save generated notes");
    } finally {
      setSaving(false);
    }
  };

  if (contentTree.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-center">
        <div>
          <FileText className="size-8 mx-auto mb-3 text-muted-foreground/40" />
          <p className="text-sm text-muted-foreground">{t("notes.empty")}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-testid="notes-section">
      <div className="px-3 py-1.5 border-b flex items-center gap-2 shrink-0">
        <span className="text-xs text-muted-foreground">{t("notes.toc")}</span>
        {loadingSaved ? (
          <span className="text-[11px] text-muted-foreground">Loading saved notes...</span>
        ) : savedBatches.length > 0 ? (
          <span className="text-[11px] text-muted-foreground">
            {savedBatches.length} saved batch{savedBatches.length > 1 ? "es" : ""}
          </span>
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-6 px-2 text-xs"
            onClick={() => void handleGenerate()}
            disabled={!selectedNode?.content || generating}
          >
            {generating ? "Generating..." : t("notes.regenerate")}
          </Button>
          <Button
            size="sm"
            className="h-6 px-2 text-xs"
            onClick={() => void handleSave()}
            disabled={!generatedNotes?.ai_content || saving}
          >
            {saving ? "Saving..." : "Save AI Notes"}
          </Button>
        </div>
      </div>

      <div className="flex-1 grid min-h-0 lg:grid-cols-[320px,1fr]">
        <ScrollArea className="border-r border-border">
          <div className="py-2">
            {contentTree.map((node) => (
              <ContentTreeNode
                key={node.id}
                node={node}
                depth={0}
                selectedId={selectedNodeId}
                onSelect={(nextNode) => {
                  setSelectedNodeId(nextNode.id);
                  setGeneratedNotes(null);
                  setMessage(null);
                  setError(null);
                }}
              />
            ))}
          </div>
        </ScrollArea>

        <div className="min-h-0 flex flex-col">
          <div className="border-b border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-muted-foreground" />
              <h3 className="text-sm font-medium">
                {generatedNotes
                  ? `${generatedNotes.original_title} · AI Notes`
                  : selectedNode?.title || t("notes.title")}
              </h3>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {generatedNotes
                ? `Generated in ${generatedNotes.format_used} format.`
                : latestSavedBatch
                  ? "Showing the latest saved AI notes or selected source content."
                  : "Select a node with content and generate AI notes."}
            </p>
          </div>

          <ScrollArea className="flex-1">
            <div className="p-4">
              {previewContent ? (
                <div className="whitespace-pre-wrap text-sm leading-6 text-foreground">
                  {previewContent}
                </div>
              ) : (
                <div className="py-10 text-center">
                  <p className="text-sm text-muted-foreground">
                    {t("notes.empty")}
                  </p>
                </div>
              )}
            </div>
          </ScrollArea>

          {(message || error) && (
            <div className={`border-t border-border px-4 py-3 text-xs ${
              error ? "text-destructive" : "text-muted-foreground"
            }`}>
              {error || message}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
