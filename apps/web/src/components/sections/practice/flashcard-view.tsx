"use client";

import { useCallback, useEffect, useState } from "react";
import { useT } from "@/lib/i18n-context";
import {
  getDueFlashcards,
  reviewFlashcard,
  type Flashcard,
  type DueFlashcardsResult,
} from "@/lib/api";
import { Button } from "@/components/ui/button";

interface FlashcardViewProps {
  courseId: string;
}

const RATINGS = [
  { label: "Again", value: 1, variant: "destructive" as const },
  { label: "Hard", value: 2, variant: "outline" as const },
  { label: "Good", value: 3, variant: "secondary" as const },
  { label: "Easy", value: 4, variant: "default" as const },
];

export function FlashcardView({ courseId }: FlashcardViewProps) {
  const t = useT();
  const [cards, setCards] = useState<Flashcard[]>([]);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [reviewed, setReviewed] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getDueFlashcards(courseId)
      .then((res: DueFlashcardsResult) => {
        if (!cancelled) {
          setCards(res.cards);
          setIndex(0);
          setFlipped(false);
          setReviewed(0);
        }
      })
      .catch(() => {
        if (!cancelled) setCards([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [courseId]);

  const handleFlip = useCallback(() => {
    if (!submitting) setFlipped((f) => !f);
  }, [submitting]);

  const handleRate = useCallback(
    async (value: number) => {
      const card = cards[index];
      if (!card || submitting) return;
      setSubmitting(true);
      try {
        await reviewFlashcard(card, value);
      } catch {
        /* best-effort */
      }
      setSubmitting(false);
      setFlipped(false);
      setReviewed((r) => r + 1);
      setIndex((i) => i + 1);
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
        <h3 className="text-sm font-medium mb-1">{t("flashcard.title")}</h3>
        <p className="text-xs text-muted-foreground max-w-xs">
          {t("flashcard.empty")}
        </p>
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
      {/* Progress counter */}
      <p className="text-xs text-muted-foreground">
        {reviewed}/{cards.length} reviewed
      </p>

      {/* Card with flip animation */}
      <div
        className="flashcard-perspective w-full max-w-md cursor-pointer"
        onClick={handleFlip}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") handleFlip(); }}
      >
        <div className={`flashcard-inner relative w-full min-h-[200px] ${flipped ? "flipped" : ""}`}>
          {/* Front */}
          <div className="flashcard-face absolute inset-0 flex flex-col items-center justify-center rounded-lg border border-border bg-card p-6 text-center">
            <p className="text-xs text-muted-foreground mb-2">Question</p>
            <p className="text-sm font-medium whitespace-pre-wrap">{card.front}</p>
          </div>

          {/* Back */}
          <div className="flashcard-back absolute inset-0 flex flex-col items-center justify-center rounded-lg border border-border bg-card p-6 text-center">
            <p className="text-xs text-muted-foreground mb-2">Answer</p>
            <p className="text-sm font-medium whitespace-pre-wrap">{card.back}</p>
          </div>
        </div>
      </div>

      {/* Tap hint or rating buttons */}
      {!flipped ? (
        <p className="text-xs text-muted-foreground">Tap card to reveal answer</p>
      ) : (
        <div className="flex gap-2">
          {RATINGS.map((r) => (
            <Button
              key={r.value}
              size="sm"
              variant={r.variant}
              disabled={submitting}
              onClick={(e) => {
                e.stopPropagation();
                handleRate(r.value);
              }}
            >
              {r.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
