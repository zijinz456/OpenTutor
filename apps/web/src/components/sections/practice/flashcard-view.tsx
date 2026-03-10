"use client";

import { useCallback, useEffect, useState } from "react";
import { useT } from "@/lib/i18n-context";
import {
  generateFlashcards,
  getDueFlashcards,
  listGeneratedFlashcardBatches,
  reviewFlashcard,
  saveGeneratedFlashcards,
  type Flashcard,
} from "@/lib/api";
import { getLectorOrderedFlashcards, type LectorFlashcard } from "@/lib/api/practice";
import { useBatchManager } from "@/hooks/use-batch-manager";
import { useWorkspaceStore } from "@/store/workspace";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AiFeatureBlocked } from "@/components/shared/ai-feature-blocked";
import { FlashcardCard } from "./flashcard-card";
import { toast } from "sonner";

interface FlashcardViewProps {
  courseId: string;
  aiActionsEnabled?: boolean;
}

export function FlashcardView({
  courseId,
  aiActionsEnabled = true,
}: FlashcardViewProps) {
  const t = useT();
  const refreshKey = useWorkspaceStore((s) => s.sectionRefreshKey["practice"]);
  const { saving, latestBatch, wrapSave } = useBatchManager({
    courseId,
    refreshSection: "practice",
    listFn: listGeneratedFlashcardBatches,
  });
  const [cards, setCards] = useState<(Flashcard | LectorFlashcard)[]>([]);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [reviewed, setReviewed] = useState(0);
  const [dueCount, setDueCount] = useState(0);
  const [useLector, setUseLector] = useState(false);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        // Try LECTOR-ordered cards first for semantically-aware review
        const lector = await getLectorOrderedFlashcards(courseId);
        if (cancelled) return;
        if (lector.cards.length > 0) {
          setCards(lector.cards);
          setDueCount(lector.count);
          setUseLector(true);
        } else {
          // Fall back to regular FSRS due cards
          const due = await getDueFlashcards(courseId);
          if (cancelled) return;
          setCards(due.cards);
          setDueCount(due.due_count);
          setUseLector(false);
        }
        setIndex(0);
        setFlipped(false);
        setReviewed(0);
      } catch {
        // Fall back to regular due cards on any error
        try {
          const due = await getDueFlashcards(courseId);
          if (!cancelled) {
            setCards(due.cards);
            setDueCount(due.due_count);
            setUseLector(false);
          }
        } catch {
          if (!cancelled) {
            setCards([]);
            setDueCount(0);
            setLoadError(t("flashcard.loadFailed"));
          }
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [courseId, refreshKey, retryCount]);

  const handleGenerate = useCallback(async () => {
    setLoading(true);
    try {
      const mode = useWorkspaceStore.getState().spaceLayout.mode ?? undefined;
      const data = await generateFlashcards(courseId, 5, mode);
      setCards(data.cards);
      setIndex(0);
      setFlipped(false);
      setReviewed(0);
      toast.success(`Generated ${data.count} flashcards`);
    } catch (error) {
      toast.error((error as Error).message || "Failed to generate flashcards");
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  const handleSave = useCallback(
    async (replaceBatchId?: string) => {
      if (cards.length === 0) return;
      await wrapSave(() =>
        saveGeneratedFlashcards(courseId, cards, "Flashcard Set", replaceBatchId),
      );
    },
    [cards, courseId, wrapSave],
  );

  const handleFlip = useCallback(() => {
    if (!submitting) setFlipped((value) => !value);
  }, [submitting]);

  const handleRate = useCallback(
    async (value: number) => {
      const card = cards[index];
      if (!card || submitting) return;
      setSubmitting(true);
      try {
        await reviewFlashcard(card, value);
      } catch {
        setReviewError(t("flashcard.reviewFailed"));
        setTimeout(() => setReviewError(null), 3000);
      }
      setSubmitting(false);
      setFlipped(false);
      setReviewed((count) => count + 1);
      setIndex((current) => current + 1);
    },
    [cards, index, submitting],
  );

  // Keyboard shortcuts: 1-4 for ratings when card is flipped
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      if (flipped && !submitting) {
        const key = parseInt(e.key, 10);
        if (key >= 1 && key <= 4) {
          e.preventDefault();
          void handleRate(key);
        }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [flipped, submitting, handleRate]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8" role="status" aria-live="polite">
        <p className="text-xs text-muted-foreground">{t("flashcard.title")}...</p>
      </div>
    );
  }

  if (cards.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        {dueCount > 0 ? (
          <Badge variant="destructive" className="mb-3">
            {dueCount} cards due today
          </Badge>
        ) : null}
        <h3 className="text-sm font-medium mb-1">{t("flashcard.title")}</h3>
        {loadError ? (
          <div role="alert" className="text-center space-y-2">
            <p className="text-sm text-destructive">{loadError}</p>
            <button type="button" onClick={() => { setLoadError(null); setLoading(true); setRetryCount((c) => c + 1); }}
              className="text-xs text-brand hover:underline">
              {t("common.retry")}
            </button>
          </div>
        ) : (
          <>
            <p className="text-xs text-muted-foreground max-w-xs">
              {t("flashcard.empty")}
            </p>
            {!aiActionsEnabled ? <AiFeatureBlocked compact className="mt-3 w-full max-w-sm text-left" /> : null}
            <Button className="mt-3" size="sm" onClick={() => void handleGenerate()} disabled={!aiActionsEnabled}>
              {t("flashcard.generate")}
            </Button>
          </>
        )}
      </div>
    );
  }

  if (index >= cards.length) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center gap-2">
        <h3 className="text-sm font-medium">{t("flashcard.title")}</h3>
        <p className="text-xs text-muted-foreground">
          All done! {reviewed}/{cards.length} reviewed.
        </p>
      </div>
    );
  }

  const card = cards[index];

  return (
    <div role="region" aria-label={t("flashcard.title")} className="flex-1 flex flex-col items-center justify-center gap-6 p-6">
      <div className="flex w-full max-w-md items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge variant="outline">
            {reviewed}/{cards.length} reviewed
          </Badge>
          {useLector && (card as LectorFlashcard).lector_reason && (card as LectorFlashcard).lector_reason !== "due" ? (
            <Badge variant="secondary" className="text-[10px]">
              {(card as LectorFlashcard).lector_reason}
            </Badge>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {latestBatch ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => void handleSave(latestBatch.batch_id)}
              disabled={saving || submitting}
            >
              Replace Latest
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="outline"
            onClick={() => void handleSave()}
            disabled={saving || submitting}
          >
            Save New
          </Button>
        </div>
      </div>

      <FlashcardCard
        card={card}
        flipped={flipped}
        submitting={submitting}
        reviewError={reviewError}
        onFlip={handleFlip}
        onRate={handleRate}
      />
    </div>
  );
}
