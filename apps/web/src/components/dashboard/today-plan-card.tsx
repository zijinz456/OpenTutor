"use client";

/**
 * TodayPlanCard — Visual Shell V2 Part A.
 *
 * Calm 3-step ordered plan that mounts above the mission hero. Answers
 * "what do I do now?" without taking the role of a primary CTA stack.
 *
 * Steps:
 *   1. Review block (gated by `totalDueFlashcards`).
 *   2. Current mission (or "pick a track" fallback).
 *   3. Lightweight recap / re-entry line.
 *
 * Frontend-only — uses existing dashboard data. No new API calls.
 */

import Link from "next/link";
import type { CurrentMissionResponse } from "@/lib/api/paths";

export interface TodayPlanCardProps {
  totalDueFlashcards: number;
  mission: CurrentMissionResponse | null | undefined;
  lastSessionAt?: string | null;
}

export function TodayPlanCard({
  totalDueFlashcards,
  mission,
  lastSessionAt,
}: TodayPlanCardProps) {
  const reviewDue = totalDueFlashcards > 0;
  const reviewTitle = reviewDue ? "Review first" : "Review clear";
  const reviewSubline = reviewDue
    ? `${totalDueFlashcards} cards due`
    : "Nothing due. Ready for new ground.";

  const hasMission = !!mission;
  const missionTitle = hasMission ? `Mission: ${mission.title}` : "Pick a track";
  const missionSubline = hasMission
    ? `${mission.task_complete}/${mission.task_total} tasks · ~${mission.eta_minutes} min`
    : "Browse tracks to start one.";

  // Step 3 — calm carry-forward Link, not a primary CTA. Copy varies based
  // on whether the user has a recent session to wrap up.
  const recapTitle = lastSessionAt
    ? "Recap last session in 2 min"
    : "Wrap up with a short recap";

  return (
    <section
      data-testid="today-plan-card"
      aria-label="Today plan"
      className="rounded-2xl border border-border bg-card p-5 card-shadow md:p-6"
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        Today plan
      </p>
      <ol className="mt-4 flex flex-col gap-4">
        <li
          data-testid="today-plan-step-review"
          className="flex gap-3"
        >
          <span className="shrink-0 text-sm font-semibold text-muted-foreground">
            1.
          </span>
          <div className="flex flex-col gap-0.5">
            <p className="text-sm font-semibold text-foreground">
              {reviewTitle}
            </p>
            <p className="text-xs text-muted-foreground">{reviewSubline}</p>
          </div>
        </li>

        <li
          data-testid="today-plan-step-mission"
          className="flex gap-3"
        >
          <span className="shrink-0 text-sm font-semibold text-muted-foreground">
            2.
          </span>
          <div className="flex flex-col gap-0.5">
            <p className="text-sm font-semibold text-foreground">
              {missionTitle}
            </p>
            <p className="text-xs text-muted-foreground">{missionSubline}</p>
          </div>
        </li>

        <li
          data-testid="today-plan-step-recap"
          className="flex gap-3"
        >
          <span className="shrink-0 text-sm font-semibold text-muted-foreground">
            3.
          </span>
          <div className="flex flex-col gap-0.5">
            <Link
              href="/session/daily"
              className="text-sm font-medium text-foreground underline-offset-4 hover:underline"
            >
              {recapTitle}
            </Link>
          </div>
        </li>
      </ol>
    </section>
  );
}
