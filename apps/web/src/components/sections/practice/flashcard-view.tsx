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
import { useBatchManager } from "@/hooks/use-batch-manager";
import { useWorkspaceStore } from "@/store/workspace";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AiFeatureBlocked } from "@/components/shared/ai-feature-blocked";
import { toast } from "sonner";

interface FlashcardViewProps {
  courseId: string;
  aiActionsEnabled?: boolean;
}

const RATINGS = [
  { label: "Again", value: 1, variant: "destructive" as const },
  { label: "Hard", value: 2, variant: "outline" as const },
  { label: "Good", value: 3, variant: "secondary" as const },
  { label: "Easy", value: 4, variant: "default" as const },
];

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
  const [cards, setCards] = useState<Flashcard[]>([]);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [reviewed, setReviewed] = useState(0);
  const [dueCount, setDueCount] = useState(0);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const due = await getDueFlashcards(courseId);
        if (cancelled) return;
        setCards(due.cards);
        setDueCount(due.due_count);
        setIndex(0);
        setFlipped(false);
        setReviewed(0);
      } catch {
        if (!cancelled) {
          setCards([]);
          setDueCount(0);
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
  }, [courseId, refreshKey]);

  const handleGenerate = useCallback(async () => {
    setLoading(true);
    try {
      const data = await generateFlashcards(courseId, 5);
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
        // best-effort
      }
      setSubmitting(false);
      setFlipped(false);
      setReviewed((count) => count + 1);
      setIndex((current) => current + 1);
    },
    [cards, index, submitting],
  );

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
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
        <p className="text-xs text-muted-foreground max-w-xs">
          {t("flashcard.empty")}
        </p>
        {!aiActionsEnabled ? <AiFeatureBlocked compact className="mt-3 w-full max-w-sm text-left" /> : null}
        <Button className="mt-3" size="sm" onClick={() => void handleGenerate()} disabled={!aiActionsEnabled}>
          {t("flashcard.generate")}
        </Button>
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
    <div className="flex-1 flex flex-col items-center justify-center gap-6 p-6">
      <div className="flex w-full max-w-md items-center justify-between gap-2">
        <Badge variant="outline">
          {reviewed}/{cards.length} reviewed
        </Badge>
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

      <div
        className="flashcard-perspective w-full max-w-md cursor-pointer"
        onClick={handleFlip}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") handleFlip();
        }}
      >
        <div className={`flashcard-inner relative w-full min-h-[200px] ${flipped ? "flipped" : ""}`}>
          <div className="flashcard-face absolute inset-0 flex flex-col items-center justify-center rounded-lg border border-border bg-card p-6 text-center">
            <p className="text-xs text-muted-foreground mb-2">Question</p>
            <p className="text-sm font-medium whitespace-pre-wrap">{card.front}</p>
          </div>

          <div className="flashcard-back absolute inset-0 flex flex-col items-center justify-center rounded-lg border border-border bg-card p-6 text-center">
            <p className="text-xs text-muted-foreground mb-2">Answer</p>
            <p className="text-sm font-medium whitespace-pre-wrap">{card.back}</p>
          </div>
        </div>
      </div>

      {!flipped ? (
        <p className="text-xs text-muted-foreground">Tap card to reveal answer</p>
      ) : (
        <div className="flex gap-2">
          {RATINGS.map((rating) => (
            <Button
              key={rating.value}
              size="sm"
              variant={rating.variant}
              disabled={submitting}
              onClick={(e) => {
                e.stopPropagation();
                void handleRate(rating.value);
              }}
            >
              {rating.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
