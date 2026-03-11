"use client";

import { useRef } from "react";
import { Button } from "@/components/ui/button";
import { useSwipeGesture } from "./use-swipe-gesture";
import type { Flashcard, LectorFlashcard } from "@/lib/api";

interface FlashcardCardProps {
  card: Flashcard | LectorFlashcard;
  flipped: boolean;
  submitting: boolean;
  reviewError: string | null;
  onFlip: () => void;
  onRate: (value: number) => void;
  t: (key: string) => string;
}

export function FlashcardCard({
  card,
  flipped,
  submitting,
  reviewError,
  onFlip,
  onRate,
  t,
}: FlashcardCardProps) {
  const cardRef = useRef<HTMLDivElement>(null);

  const ratings = [
    { label: t("flashcard.again"), value: 1, variant: "destructive" as const },
    { label: t("flashcard.hard"), value: 2, variant: "outline" as const },
    { label: t("flashcard.good"), value: 3, variant: "secondary" as const },
    { label: t("flashcard.easy"), value: 4, variant: "default" as const },
  ];

  const { swipeStyle, handlers } = useSwipeGesture({
    enabled: flipped,
    onSwipeRight: () => void onRate(3),
    onSwipeLeft: () => void onRate(1),
  });

  return (
    <>
      <div
        ref={cardRef}
        className="flashcard-perspective w-full max-w-md cursor-pointer touch-none"
        onClick={onFlip}
        role="button"
        tabIndex={0}
        aria-label={
          flipped
            ? t("flashcard.ariaAnswer")
            : t("flashcard.ariaQuestion")
        }
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onFlip();
          }
        }}
        {...handlers}
        style={swipeStyle}
      >
        <div
          aria-live="polite"
          className={`flashcard-inner relative w-full min-h-[200px] ${flipped ? "flipped" : ""}`}
        >
          <div className="flashcard-face absolute inset-0 flex flex-col items-center justify-center rounded-2xl card-shadow bg-card p-6 text-center">
            <p className="text-xs text-muted-foreground mb-2">{t("flashcard.questionLabel")}</p>
            <p className="text-sm font-medium whitespace-pre-wrap">{card.front}</p>
          </div>

          <div className="flashcard-back absolute inset-0 flex flex-col items-center justify-center rounded-2xl card-shadow bg-card p-6 text-center">
            <p className="text-xs text-muted-foreground mb-2">{t("flashcard.answerLabel")}</p>
            <p className="text-sm font-medium whitespace-pre-wrap">{card.back}</p>
          </div>
        </div>
      </div>

      {!flipped ? (
        <p className="text-xs text-muted-foreground">
          {t("flashcard.tapToReveal")}
        </p>
      ) : (
        <div className="flex flex-col items-center gap-1.5">
          <div className="flex gap-2">
            {ratings.map((rating) => (
              <Button
                key={rating.value}
                size="sm"
                variant={rating.variant}
                disabled={submitting}
                aria-label={`Rate: ${rating.label} (press ${rating.value})`}
                aria-keyshortcuts={String(rating.value)}
                onClick={(e) => {
                  e.stopPropagation();
                  void onRate(rating.value);
                }}
              >
                {rating.label}
              </Button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground/60">{t("flashcard.pressToRate")}</p>
        </div>
      )}
      {reviewError && (
        <p role="alert" className="text-xs text-warning-foreground text-center mt-2">
          {reviewError}
        </p>
      )}
    </>
  );
}
