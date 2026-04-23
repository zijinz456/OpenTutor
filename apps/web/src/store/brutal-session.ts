/**
 * Zustand store for the Brutal Drill session runner (Phase 6 T2).
 *
 * Mirrors `daily-session.ts` shape but holds the distinctive Brutal
 * machinery: a mutable card queue, a force-retire cap, streak tracking,
 * and a per-concept failure tally for the closure screen.
 *
 * Semantics
 * ---------
 * * **In-memory only.** Same rationale as `daily-session.ts` — we never
 *   persist session state. Brutal has an even stronger case: the mode
 *   exists to collapse one intense sitting; "resume where you left off"
 *   would re-pressurise a user who already bailed.
 *
 * * **Queue is a FIFO with requeue-on-wrong.** Wrong answers push the
 *   card back to the tail (`shift` then `push`). Correct answers drop
 *   the card permanently (`shift`, mark mastered). Session ends when
 *   `queue` is empty (equivalently: `mastered.size >= plan.cards.length`).
 *
 * * **MAX_ATTEMPTS = 10 force-retire.** Critic fix #1 from the phase
 *   plan. Without this, a user who has never seen the underlying
 *   concept can loop a card forever. At 10 attempts we:
 *     1. Mark the card mastered (so it leaves the queue).
 *     2. Add it to `forceRetired` for the closure diagnostic.
 *     3. Reset streak (consistent with wrong-answer semantics).
 *   The closure screen renders "N cards hit the 10-attempt cap — consider
 *   editing those cards" so the learner has signal, not just silence.
 *
 * * **Concept fail tally** accumulates `concept_slug` strings from the
 *   card's `problem_metadata` on every WRONG answer, including force-retire.
 *   The closure screen renders the top-3 weakest concepts. Cards missing a
 *   `concept_slug` contribute to `__unlabeled__` — better than dropping the
 *   signal, since a recurring unlabeled fail still means *something* weak.
 *
 * * **Streak tracks current session only.** `currentStreak` increments on
 *   correct, resets on wrong (including force-retire). `maxStreak` is the
 *   running max. Not persisted across sessions per MASTER §8 (no guilt-via-
 *   streak) — Brutal's streak is a here-and-now indicator of momentum.
 */

import { create } from "zustand";
import type {
  BrutalPlanResponse,
  BrutalSessionSize,
  DailyPlanCard,
} from "@/lib/api";

export const MAX_ATTEMPTS = 10;
/** Force-retire threshold. Public so tests can assert the cap without
 *  hard-coding the literal in two places. */

export type BrutalTimeoutMs = 15000 | 30000 | 60000;

export interface BrutalProgress {
  mastered: number;
  total: number;
}

export interface BrutalSessionState {
  // ── Config (set at start) ──
  size: BrutalSessionSize;
  timeoutMs: BrutalTimeoutMs;
  /** `Date.now()` at session start — closure screen computes elapsed. */
  startedAt: number;

  // ── Queue machinery ──
  queue: DailyPlanCard[];
  mastered: Set<string>;
  attempts: Record<string, number>;

  // ── Streak ──
  currentStreak: number;
  maxStreak: number;

  // ── Diagnostics ──
  forceRetired: Set<string>;
  conceptFailTally: Record<string, number>;

  // ── Actions ──
  /** Seed a fresh session. Wipes any prior state. `timeoutMs` is set here
   *  (not derived from size) because the two axes are independent in the
   *  picker UI. */
  start: (plan: BrutalPlanResponse, timeoutMs: BrutalTimeoutMs) => void;
  /** Record one answer and update queue + streak + tally accordingly.
   *  Callers pass the card id (not the card object) so the store is the
   *  single source of truth about what card is current — see
   *  `currentCard()` for the queue-head accessor. */
  answer: (cardId: string, correct: boolean) => void;
  /** Full reset to the initial state. Exposed for tests + the "Run
   *  another" closure button. */
  reset: () => void;

  // ── Derived ──
  currentCard: () => DailyPlanCard | null;
  progress: () => BrutalProgress;
  isFinished: () => boolean;
}

/** Default session size — echoes `BrutalSessionSize` default on the
 *  server (Query default `30`). Placeholder until `start()` is called;
 *  tests that probe the initial state rely on this. */
const INITIAL_STATE: Pick<
  BrutalSessionState,
  | "size"
  | "timeoutMs"
  | "startedAt"
  | "queue"
  | "mastered"
  | "attempts"
  | "currentStreak"
  | "maxStreak"
  | "forceRetired"
  | "conceptFailTally"
> = {
  size: 30,
  timeoutMs: 30000,
  startedAt: 0,
  queue: [],
  mastered: new Set(),
  attempts: {},
  currentStreak: 0,
  maxStreak: 0,
  forceRetired: new Set(),
  conceptFailTally: {},
};

/** Narrow pull of `concept_slug` off `problem_metadata`. Kept local to
 *  the store so the broader codebase doesn't need to care that we look
 *  at metadata by string key — if the schema hardens later, we update
 *  here without churning callers. */
function readConceptSlug(card: DailyPlanCard): string {
  const meta = card.problem_metadata;
  if (meta && typeof meta === "object") {
    const raw = (meta as Record<string, unknown>).concept_slug;
    if (typeof raw === "string" && raw.length > 0) return raw;
  }
  return "__unlabeled__";
}

export const useBrutalSessionStore = create<BrutalSessionState>((set, get) => ({
  ...INITIAL_STATE,

  start: (plan, timeoutMs) =>
    set({
      size: (plan.cards.length > 0 ? plan.size : plan.size) as BrutalSessionSize,
      timeoutMs,
      startedAt: Date.now(),
      // Clone so that callers mutating the plan array post-start don't
      // corrupt our queue (and vice versa).
      queue: [...plan.cards],
      mastered: new Set(),
      attempts: {},
      currentStreak: 0,
      maxStreak: 0,
      forceRetired: new Set(),
      conceptFailTally: {},
    }),

  answer: (cardId, correct) =>
    set((s) => {
      // Find the card — usually queue[0], but be defensive against
      // out-of-order submits (e.g. double-click) so we don't poison the
      // queue on a stale id.
      const idx = s.queue.findIndex((c) => c.id === cardId);
      if (idx === -1) return s;
      const card = s.queue[idx];

      if (correct) {
        const newQueue = [...s.queue.slice(0, idx), ...s.queue.slice(idx + 1)];
        const newMastered = new Set(s.mastered);
        newMastered.add(cardId);
        const nextStreak = s.currentStreak + 1;
        return {
          queue: newQueue,
          mastered: newMastered,
          currentStreak: nextStreak,
          maxStreak: Math.max(s.maxStreak, nextStreak),
        };
      }

      // Wrong answer: bump attempts, requeue-to-tail or force-retire,
      // reset streak, tally the concept.
      const prevAttempts = s.attempts[cardId] ?? 0;
      const nextAttempts = prevAttempts + 1;
      const slug = readConceptSlug(card);
      const newTally = {
        ...s.conceptFailTally,
        [slug]: (s.conceptFailTally[slug] ?? 0) + 1,
      };
      const newAttempts = { ...s.attempts, [cardId]: nextAttempts };

      if (nextAttempts >= MAX_ATTEMPTS) {
        // Force-retire: mark mastered so it leaves the queue, but also
        // record in forceRetired for the closure diagnostic.
        const newQueue = [
          ...s.queue.slice(0, idx),
          ...s.queue.slice(idx + 1),
        ];
        const newMastered = new Set(s.mastered);
        newMastered.add(cardId);
        const newForceRetired = new Set(s.forceRetired);
        newForceRetired.add(cardId);
        return {
          queue: newQueue,
          mastered: newMastered,
          forceRetired: newForceRetired,
          attempts: newAttempts,
          conceptFailTally: newTally,
          currentStreak: 0,
        };
      }

      // Tail-requeue: remove from current position, push to end.
      const newQueue = [
        ...s.queue.slice(0, idx),
        ...s.queue.slice(idx + 1),
        card,
      ];
      return {
        queue: newQueue,
        attempts: newAttempts,
        conceptFailTally: newTally,
        currentStreak: 0,
      };
    }),

  reset: () =>
    set({
      ...INITIAL_STATE,
      // Fresh Set / Record instances on every reset so cross-session
      // mutation can't leak via shared reference.
      mastered: new Set(),
      attempts: {},
      forceRetired: new Set(),
      conceptFailTally: {},
    }),

  currentCard: () => {
    const q = get().queue;
    return q.length > 0 ? q[0] : null;
  },

  progress: () => {
    const s = get();
    return { mastered: s.mastered.size, total: s.mastered.size + s.queue.length };
  },

  isFinished: () => {
    const s = get();
    // Session is finished when the queue is empty AND we've seen at least
    // one answer OR the plan started empty. The "started empty" case is
    // handled by the page component (it renders the closure without ever
    // calling `answer`), so here we simply report queue emptiness.
    return s.queue.length === 0 && s.startedAt > 0;
  },
}));
