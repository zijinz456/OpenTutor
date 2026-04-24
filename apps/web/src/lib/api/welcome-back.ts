/**
 * Welcome-back API helper (ADHD Phase 14 T4).
 *
 * Thin typed wrapper around `GET /api/sessions/welcome-back`. Kept in a
 * dedicated module so `practice.ts` does not bloat further; re-exported
 * from `lib/api/index.ts` for a single public barrel.
 *
 * Backend contract (commit e6554b5): returns the gap-day snapshot the
 * dashboard needs to decide whether to show the welcome-back modal, plus
 * the concept titles the user has most recently mastered.
 */

import { request } from "@/lib/api/client";

export interface WelcomeBackPayload {
  /** Whole days since the last practice submission. `null` when the user
   *  has no history at all (fresh account). */
  gap_days: number | null;
  /** ISO 8601 timestamp of the last practice submission, or `null` when
   *  the user has no history. */
  last_practice_at: string | null;
  /** Up to 3 concept titles the user mastered most recently, newest
   *  first. Empty when nothing has crossed the mastery threshold. */
  top_mastered_concepts: string[];
  /** Count of overdue review items. The modal intentionally clamps the
   *  display to `10+` so it reads as a gentle nudge, not a debt. */
  overdue_count: number;
}

export async function getWelcomeBack(): Promise<WelcomeBackPayload> {
  return request("/sessions/welcome-back");
}
