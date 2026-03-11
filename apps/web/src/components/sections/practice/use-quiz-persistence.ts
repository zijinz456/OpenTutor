/**
 * useQuizPersistence — localStorage-based quiz session persistence.
 *
 * Saves quiz progress (current index, score, answered questions) so users
 * can resume after browser close or page refresh. Auto-expires after 24h.
 */

import { useCallback } from "react";

const EXPIRY_MS = 24 * 60 * 60 * 1000; // 24 hours

export interface QuizSessionState {
  currentIdx: number;
  score: { correct: number; total: number };
  answeredMap: Record<string, string>; // problemId -> selectedOption
  consecutiveWrong: number;
  savedAt: number;
}

function storageKey(courseId: string): string {
  return `opentutor_quiz_${courseId}`;
}

export function useQuizPersistence(courseId: string) {
  const save = useCallback(
    (state: Omit<QuizSessionState, "savedAt">) => {
      try {
        const data: QuizSessionState = { ...state, savedAt: Date.now() };
        localStorage.setItem(storageKey(courseId), JSON.stringify(data));
      } catch {
        // Quota exceeded or SSR — best effort
      }
    },
    [courseId],
  );

  const load = useCallback((): QuizSessionState | null => {
    try {
      const raw = localStorage.getItem(storageKey(courseId));
      if (!raw) return null;
      const data: QuizSessionState = JSON.parse(raw);
      if (Date.now() - data.savedAt > EXPIRY_MS) {
        localStorage.removeItem(storageKey(courseId));
        return null;
      }
      return data;
    } catch {
      return null;
    }
  }, [courseId]);

  const clear = useCallback(() => {
    try {
      localStorage.removeItem(storageKey(courseId));
    } catch {
      // best effort
    }
  }, [courseId]);

  return { save, load, clear };
}

/** Flashcard-specific persistence (simpler shape). */
export interface FlashcardSessionState {
  index: number;
  reviewedCount: number;
  savedAt: number;
}

function flashcardKey(courseId: string): string {
  return `opentutor_flashcard_${courseId}`;
}

export function useFlashcardPersistence(courseId: string) {
  const save = useCallback(
    (state: Omit<FlashcardSessionState, "savedAt">) => {
      try {
        const data: FlashcardSessionState = { ...state, savedAt: Date.now() };
        localStorage.setItem(flashcardKey(courseId), JSON.stringify(data));
      } catch {
        // best effort
      }
    },
    [courseId],
  );

  const load = useCallback((): FlashcardSessionState | null => {
    try {
      const raw = localStorage.getItem(flashcardKey(courseId));
      if (!raw) return null;
      const data: FlashcardSessionState = JSON.parse(raw);
      if (Date.now() - data.savedAt > EXPIRY_MS) {
        localStorage.removeItem(flashcardKey(courseId));
        return null;
      }
      return data;
    } catch {
      return null;
    }
  }, [courseId]);

  const clear = useCallback(() => {
    try {
      localStorage.removeItem(flashcardKey(courseId));
    } catch {
      // best effort
    }
  }, [courseId]);

  return { save, load, clear };
}
