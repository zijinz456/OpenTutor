"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useBatchManager } from "@/hooks/use-batch-manager";
import { listGeneratedQuizBatches, saveGeneratedQuiz } from "@/lib/api";
import { useChatStore } from "@/store/chat";
import { useWorkspaceStore } from "@/store/workspace";
import { toast } from "sonner";

interface GeneratedQuizCardProps {
  courseId: string;
}

export function GeneratedQuizCard({ courseId }: GeneratedQuizCardProps) {
  const draft = useChatStore((s) => s.generatedQuizDraft);
  const parseError = useChatStore((s) => s.generatedQuizError);
  const clearGeneratedQuizDraft = useChatStore((s) => s.clearGeneratedQuizDraft);
  const triggerRefresh = useWorkspaceStore((s) => s.triggerRefresh);
  const [saving, setSaving] = useState(false);
  const { latestBatch, loadBatches } = useBatchManager({
    courseId,
    refreshSection: "practice",
    listFn: listGeneratedQuizBatches,
  });

  if (!draft && !parseError) {
    return null;
  }

  const handleSave = async (replaceBatchId?: string) => {
    if (!draft) return;
    setSaving(true);
    try {
      const result = await saveGeneratedQuiz(
        courseId,
        draft.rawContent,
        "Chat-generated practice set",
        replaceBatchId,
      );
      toast.success(`Saved ${result.saved} questions to the course quiz bank`);
      triggerRefresh("practice");
      await loadBatches();
      clearGeneratedQuizDraft(courseId);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to save generated quiz");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="border-t border-border/60 bg-muted/20 px-3 py-2">
      <div className="rounded-xl border border-border/70 bg-background px-3 py-2.5" data-testid="generated-quiz-card">
        {draft ? (
          <>
            <p className="text-sm font-medium text-foreground">Generated questions detected</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {draft.questionCount} question{draft.questionCount === 1 ? "" : "s"} ready to save to the course quiz bank.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {latestBatch?.is_active ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={saving}
                  onClick={() => void handleSave(latestBatch.batch_id)}
                >
                  Replace Latest
                </Button>
              ) : null}
              <Button type="button" size="sm" disabled={saving} onClick={() => void handleSave()}>
                Save New
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={saving}
                onClick={() => clearGeneratedQuizDraft(courseId)}
              >
                Dismiss
              </Button>
            </div>
          </>
        ) : (
          <>
            <p className="text-sm font-medium text-foreground">Generated quiz not saved</p>
            <p className="mt-1 text-xs text-muted-foreground">{parseError}</p>
            <div className="mt-3">
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => clearGeneratedQuizDraft(courseId)}
              >
                Dismiss
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
