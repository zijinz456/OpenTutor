/**
 * Zustand store for the ADHD daily-session flow (Phase 13 T3).
 *
 * Holds the cards fetched by `<DailySessionCTA>`, the cursor for the
 * `/session/daily` route, and a tiny stats tally for `<SessionClosure>`.
 *
 * Design notes
 * ------------
 * * **In-memory only.** MASTER §8 is explicit that refreshing a quick
 *   session is fine as "start over" — persisting to localStorage would
 *   tempt us to add "resume where you left off" prompts that recreate the
 *   guilt pattern we're trying to kill. Keep state ephemeral.
 * * **`finished` flips once per session.** We intentionally compute it
 *   inside `recordAnswer` (not as a selector) so subscribers that gate
 *   route transitions ("if finished → render closure") don't miss the
 *   edge. `advance` moves the cursor forward bounded by `size - 1`; the
 *   page component chooses whether to advance or render closure based on
 *   `finished`.
 * * **`reset` is called implicitly by `start`.** Starting a new session
 *   (either from the dashboard CTA or the closure "Do 1 more?" button)
 *   wipes prior state — we don't accumulate across sessions because the
 *   closure's purpose is "the moment you feel done".
 */

import { create } from "zustand";
import type { DailyPlanCard, DailySessionSize } from "@/lib/api";

export interface DailySessionStats {
  correct: number;
  wrong: number;
}

export interface DailySessionState {
  cards: DailyPlanCard[];
  currentIdx: number;
  answered: number;
  size: DailySessionSize;
  finished: boolean;
  stats: DailySessionStats;

  /** Seed a fresh session. Empties prior state even if the new pool is
   *  smaller than the previous one — see reset-on-start note in the
   *  module docstring. */
  start: (size: DailySessionSize, cards: DailyPlanCard[]) => void;
  /** Record one answer. Increments stats and flips `finished` when the
   *  running answered count reaches either `size` or `cards.length`
   *  (whichever is smaller — guards against a backend partial fill). */
  recordAnswer: (is_correct: boolean) => void;
  /** Move the cursor one card forward, bounded by the card count. The
   *  page component calls this after a ~500ms feedback delay. */
  advance: () => void;
  /** Full reset to the initial state. Exposed for tests + the closure
   *  "Back to dashboard" button (so re-opening the dashboard doesn't
   *  leak stale `finished=true` into the next CTA click). */
  reset: () => void;
}

const INITIAL_STATE: Omit<
  DailySessionState,
  "start" | "recordAnswer" | "advance" | "reset"
> = {
  cards: [],
  currentIdx: 0,
  answered: 0,
  size: 5,
  finished: false,
  stats: { correct: 0, wrong: 0 },
};

export const useDailySessionStore = create<DailySessionState>((set) => ({
  ...INITIAL_STATE,

  start: (size, cards) =>
    set({
      cards,
      size,
      currentIdx: 0,
      answered: 0,
      finished: cards.length === 0,
      stats: { correct: 0, wrong: 0 },
    }),

  recordAnswer: (is_correct) =>
    set((s) => {
      const nextAnswered = s.answered + 1;
      const cap = Math.min(s.size, s.cards.length);
      return {
        answered: nextAnswered,
        stats: {
          correct: s.stats.correct + (is_correct ? 1 : 0),
          wrong: s.stats.wrong + (is_correct ? 0 : 1),
        },
        finished: nextAnswered >= cap,
      };
    }),

  advance: () =>
    set((s) => ({
      currentIdx: Math.min(s.currentIdx + 1, Math.max(0, s.cards.length - 1)),
    })),

  reset: () => set({ ...INITIAL_STATE }),
}));
