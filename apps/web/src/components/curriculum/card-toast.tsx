"use client";

/**
 * Card-candidate toast — §14.5 v2.1 T7 minimum viable UI.
 *
 * Mounted when the chat stream emits a `pending_cards` SSE event.
 * Polls `/card-candidates` on mount. When the spawner returned cards,
 * surfaces a Save / Dismiss prompt. On Save, POSTs to
 * `/save-candidates` and briefly shows "Saved!" before dismissing.
 * When the backend returns zero cards (or the poll times out) the
 * component renders nothing and auto-clears itself from the store.
 */

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  getCardCandidates,
  saveCardCandidates,
  type CardCandidate,
} from "@/lib/api/curriculum";
import { useChatStore } from "@/store/chat";

interface CardToastProps {
  courseId: string;
  sessionId: string;
  messageId: string;
}

type ToastPhase = "loading" | "prompt" | "saving" | "saved" | "hidden";

interface ToastState {
  phase: ToastPhase;
  cards: CardCandidate[];
}

export function CardToast({ courseId, sessionId, messageId }: CardToastProps) {
  const clearPendingCards = useChatStore((s) => s.clearPendingCards);
  const [state, setState] = useState<ToastState>({
    phase: "loading",
    cards: [],
  });
  const { phase, cards } = state;

  // Fetch candidates when mounted.
  useEffect(() => {
    let cancelled = false;
    getCardCandidates(sessionId, messageId)
      .then((resp) => {
        if (cancelled) return;
        const received = resp.cards ?? [];
        if (received.length === 0) {
          setState({ phase: "hidden", cards: [] });
          clearPendingCards();
          return;
        }
        setState({ phase: "prompt", cards: received });
      })
      .catch(() => {
        if (cancelled) return;
        // Silent failure — candidate fetch is best-effort UX.
        setState({ phase: "hidden", cards: [] });
        clearPendingCards();
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, messageId, clearPendingCards]);

  // Auto-hide after "Saved!" flash.
  useEffect(() => {
    if (phase !== "saved") return;
    const t = setTimeout(() => {
      setState({ phase: "hidden", cards: [] });
      clearPendingCards();
    }, 2000);
    return () => clearTimeout(t);
  }, [phase, clearPendingCards]);

  if (phase === "loading" || phase === "hidden") {
    return null;
  }

  const handleSave = async () => {
    setState((prev) => ({ ...prev, phase: "saving" }));
    try {
      await saveCardCandidates(courseId, cards);
      setState((prev) => ({ ...prev, phase: "saved" }));
    } catch {
      // Leave the prompt up so the user can retry / dismiss.
      setState((prev) => ({ ...prev, phase: "prompt" }));
    }
  };

  const handleDismiss = () => {
    setState({ phase: "hidden", cards: [] });
    clearPendingCards();
  };

  return (
    <div
      role="region"
      aria-label="Flashcard candidates"
      data-testid="card-toast"
      className="mx-3 mb-2 flex items-center justify-between gap-3 rounded-md border border-border bg-card px-3 py-2 text-sm"
    >
      {phase === "saved" ? (
        <span className="text-xs font-medium text-primary" data-testid="card-toast-saved">
          Saved!
        </span>
      ) : (
        <>
          <span>
            Save {cards.length} card{cards.length === 1 ? "" : "s"}?
          </span>
          <div className="flex gap-1.5">
            <Button
              type="button"
              size="sm"
              variant="default"
              onClick={handleSave}
              disabled={phase === "saving"}
              data-testid="card-toast-save"
            >
              {phase === "saving" ? "Saving..." : "Save"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={handleDismiss}
              disabled={phase === "saving"}
              data-testid="card-toast-dismiss"
            >
              Dismiss
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
