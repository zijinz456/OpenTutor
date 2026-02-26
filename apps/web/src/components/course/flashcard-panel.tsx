"use client";

import { useState } from "react";
import { Loader2, RotateCcw, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Flashcard {
  id: string;
  front: string;
  back: string;
  difficulty: string;
  fsrs: {
    difficulty: number;
    stability: number;
    reps: number;
    state: string;
    due: string | null;
  };
}

interface FlashcardPanelProps {
  courseId: string;
}

export function FlashcardPanel({ courseId }: FlashcardPanelProps) {
  const [cards, setCards] = useState<Flashcard[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [reviewing, setReviewing] = useState(false);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const res = await fetch(`${API_BASE}/api/flashcards/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ course_id: courseId, count: 10 }),
      });
      const data = await res.json();
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

  const handleReview = async (rating: number) => {
    if (!cards[currentIndex]) return;
    setReviewing(true);

    try {
      const res = await fetch(`${API_BASE}/api/flashcards/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ card: cards[currentIndex], rating }),
      });
      const data = await res.json();

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

  // Empty state
  if (cards.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4 text-center">
        <div>
          <p className="text-muted-foreground text-sm mb-3">No flashcards yet</p>
          <Button onClick={handleGenerate} disabled={generating} size="sm">
            {generating ? (
              <>
                <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                Generating...
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4 mr-1" />
                Generate Flashcards
              </>
            )}
          </Button>
        </div>
      </div>
    );
  }

  const card = cards[currentIndex];
  const dueCount = cards.filter(
    (c) => !c.fsrs.due || new Date(c.fsrs.due) <= new Date()
  ).length;

  return (
    <div className="flex-1 flex flex-col">
      {/* Header */}
      <div className="px-3 py-2 border-b flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Card {currentIndex + 1} of {cards.length}
        </span>
        <div className="flex gap-2">
          <Badge variant="outline">{dueCount} due</Badge>
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
              {flipped ? "Answer" : "Question"}
            </div>
            <div className="flex items-center justify-center min-h-[150px]">
              <p className="text-center text-sm leading-relaxed">
                {flipped ? card.back : card.front}
              </p>
            </div>
            <div className="absolute bottom-2 right-3 text-xs text-muted-foreground">
              <RotateCcw className="h-3 w-3 inline mr-1" />
              Click to flip
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
            Again
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleReview(2)}
            disabled={reviewing}
          >
            Hard
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={() => handleReview(3)}
            disabled={reviewing}
          >
            Good
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleReview(4)}
            disabled={reviewing}
          >
            Easy
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
            Prev
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
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
