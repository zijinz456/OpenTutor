"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, Loader2, RotateCcw, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  generateFlashcards,
  getDueFlashcards,
  listGeneratedFlashcardBatches,
  reviewFlashcard,
  saveGeneratedFlashcards,
  type Flashcard,
  type GeneratedAssetBatchSummary,
} from "@/lib/api";
import { toast } from "sonner";
import { useT } from "@/lib/i18n-context";

interface FlashcardPanelProps {
  courseId: string;
}

export function FlashcardPanel({ courseId }: FlashcardPanelProps) {
  const t = useT();
  const [cards, setCards] = useState<Flashcard[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [batches, setBatches] = useState<GeneratedAssetBatchSummary[]>([]);
  const [dueCount, setDueCount] = useState(0);

  const loadBatches = useCallback(async () => {
    try {
      setBatches(await listGeneratedFlashcardBatches(courseId));
    } catch {
      setBatches([]);
    }
  }, [courseId]);

  const loadDueCards = useCallback(async () => {
    try {
      const data = await getDueFlashcards(courseId);
      setDueCount(data.due_count);
    } catch {
      setDueCount(0);
    }
  }, [courseId]);

  useEffect(() => {
    void loadBatches();
    void loadDueCards();
  }, [loadBatches, loadDueCards]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const data = await generateFlashcards(courseId, 10);
      setCards(data.cards || []);
      setCurrentIndex(0);
      setFlipped(false);
      toast.success(`Generated ${data.count} flashcards`);
    } catch {
      toast.error("Failed to generate flashcards");
    } finally {
      setGenerating(false);
    }
  };

  const handleSave = async (replaceBatchId?: string) => {
    if (cards.length === 0) return;
    setSaving(true);
    try {
      const result = await saveGeneratedFlashcards(courseId, cards, "Flashcard Set", replaceBatchId);
      toast.success(result.replaced ? `Replaced flashcards with version ${result.version}` : "Saved flashcard set");
      await loadBatches();
    } catch (error) {
      toast.error((error as Error).message || "Failed to save flashcards");
    } finally {
      setSaving(false);
    }
  };

  const handleReview = async (rating: number) => {
    if (!cards[currentIndex]) return;
    setReviewing(true);

    try {
      const data = await reviewFlashcard(cards[currentIndex], rating);

      // Update card in list
      const updated = [...cards];
      updated[currentIndex] = data.card;
      setCards(updated);

      // Move to next card
      if (currentIndex < cards.length - 1) {
        setCurrentIndex((i) => i + 1);
        setFlipped(false);
      } else {
        toast.success("Review session complete!");
      }
    } catch {
      toast.error("Failed to submit review");
    } finally {
      setReviewing(false);
    }
  };

  const handleLoadDue = async () => {
    setGenerating(true);
    try {
      const data = await getDueFlashcards(courseId);
      if (data.cards.length === 0) {
        toast.info("No cards due for review right now!");
        return;
      }
      setCards(data.cards);
      setCurrentIndex(0);
      setFlipped(false);
      toast.success(`${data.due_count} cards due for review`);
    } catch {
      toast.error("Failed to load due cards");
    } finally {
      setGenerating(false);
    }
  };

  // Empty state
  if (cards.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 text-center">
        <div>
          {dueCount > 0 && (
            <div className="mb-4">
              <Badge variant="destructive" className="mb-2">{dueCount} cards due today</Badge>
              <div>
                <Button onClick={handleLoadDue} disabled={generating} size="sm" variant="default" className="mb-3">
                  <RotateCcw className="h-4 w-4 mr-1" />
                  Review Due Cards
                </Button>
              </div>
            </div>
          )}
          <p className="text-muted-foreground text-sm mb-3">{t("flashcard.empty")}</p>
          <Button onClick={handleGenerate} disabled={generating} size="sm">
            {generating ? (
              <>
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                {t("quiz.generating")}
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4 mr-1" />
                {t("flashcard.generate")}
              </>
            )}
          </Button>
        </div>
      </div>
    );
  }

  const card = cards[currentIndex];
  const currentDueCount = cards.filter(
    (c) => !c.fsrs.due || new Date(c.fsrs.due) <= new Date()
  ).length;
  const latestBatch = batches.find((batch) => batch.is_active) ?? null;

  return (
    <div className="flex-1 flex flex-col">
      {/* Header */}
      <div className="px-3 py-2 border-b flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Card {currentIndex + 1} of {cards.length}
        </span>
        <div className="flex gap-2">
          {latestBatch?.is_active && (
            <Button size="sm" variant="outline" onClick={() => handleSave(latestBatch.batch_id)} disabled={saving || generating || reviewing}>
              <Download className="h-4 w-4 mr-1" />
              Replace Latest
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={() => handleSave()} disabled={saving || generating || reviewing}>
            <Download className="h-4 w-4 mr-1" />
            Save New
          </Button>
          <Badge variant="outline">{currentDueCount} {t("flashcard.due")}</Badge>
          <Badge variant="secondary">{card.difficulty}</Badge>
        </div>
      </div>

      {/* Card */}
      <div
        className="flex-1 flex items-center justify-center p-6 cursor-pointer"
        onClick={() => setFlipped(!flipped)}
      >
        <div className="w-full max-w-md">
          <div
            className={`relative w-full min-h-[200px] p-6 rounded-lg border-2 transition-all duration-300 ${
              flipped
                ? "bg-primary/5 border-primary/30"
                : "bg-card border-border hover:border-primary/20"
            }`}
          >
            <div className="absolute top-2 left-3 text-xs text-muted-foreground">
              {flipped ? t("flashcard.back") : t("flashcard.front")}
            </div>
            <div className="flex items-center justify-center min-h-[150px]">
              <p className="text-center text-sm leading-relaxed">
                {flipped ? card.back : card.front}
              </p>
            </div>
            <div className="absolute bottom-2 right-3 text-xs text-muted-foreground">
              <RotateCcw className="h-3 w-3 inline mr-1" />
              {t("flashcard.flip")}
            </div>
          </div>
        </div>
      </div>

      {/* FSRS Rating buttons (shown after flip) */}
      {flipped && (
        <div className="border-t px-3 py-3 flex items-center justify-center gap-2">
          <Button
            variant="destructive"
            size="sm"
            onClick={() => handleReview(1)}
            disabled={reviewing}
          >
            {t("flashcard.again")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleReview(2)}
            disabled={reviewing}
          >
            {t("flashcard.hard")}
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={() => handleReview(3)}
            disabled={reviewing}
          >
            {t("flashcard.good")}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleReview(4)}
            disabled={reviewing}
          >
            {t("flashcard.easy")}
          </Button>
        </div>
      )}

      {/* Navigation when not flipped */}
      {!flipped && (
        <div className="border-t px-3 py-2 flex items-center justify-between">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setCurrentIndex((i) => Math.max(0, i - 1));
              setFlipped(false);
            }}
            disabled={currentIndex === 0}
          >
            {t("quiz.prev")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setCurrentIndex((i) => Math.min(cards.length - 1, i + 1));
              setFlipped(false);
            }}
            disabled={currentIndex >= cards.length - 1}
          >
            {t("quiz.next")}
          </Button>
        </div>
      )}
    </div>
  );
}
