"use client";

/**
 * `<GamificationWidget>` — dashboard support-rail status card
 * (Phase 16c Bundle C — Subagent B).
 *
 * Self-contained: fetches `/api/gamification/dashboard` on mount and
 * stacks `<XpLevelChip>` + `<StreakChip>` + `<SparseHeatmap>` into a
 * single calm card. Loading is a slim skeleton, error is a quiet
 * "stats unavailable" line with a retry button. No toasts, no sounds,
 * no flash — per ТЗ §11 rules 11/12 the widget is passive status.
 */

import { useCallback, useEffect, useState } from "react";
import {
  getGamificationDashboard,
  type GamificationDashboard,
} from "@/lib/api/gamification";
import { XpLevelChip } from "./xp-level-chip";
import { StreakChip } from "./streak-chip";
import { SparseHeatmap } from "./sparse-heatmap";

type WidgetState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; data: GamificationDashboard };

export function GamificationWidget() {
  const [state, setState] = useState<WidgetState>({ status: "loading" });
  // Bumping `attempt` re-runs the fetch effect — used by the retry button.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    getGamificationDashboard()
      .then((data) => {
        if (!cancelled) setState({ status: "loaded", data });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const onRetry = useCallback(() => {
    setAttempt((n) => n + 1);
  }, []);

  return (
    <section
      data-testid="gamification-widget"
      data-panic-hide
      aria-label="Progress overview"
      className="rounded-2xl border border-border bg-card p-4 card-shadow"
    >
      {state.status === "loading" && (
        <div
          data-testid="gamification-widget-loading"
          className="flex flex-col gap-3"
          aria-busy="true"
        >
          <div className="h-16 w-full rounded-2xl bg-muted/40 animate-pulse" />
          <div className="h-12 w-full rounded-2xl bg-muted/40 animate-pulse" />
          <div className="h-20 w-full rounded-2xl bg-muted/30 animate-pulse" />
        </div>
      )}

      {state.status === "error" && (
        <div
          data-testid="gamification-widget-error"
          className="flex flex-col gap-2"
        >
          <p className="text-xs text-muted-foreground">
            Couldn't load progress. Retry?
          </p>
          <button
            type="button"
            onClick={onRetry}
            data-testid="gamification-widget-retry"
            className="self-start rounded-full border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted/40 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {state.status === "loaded" && (
        <div
          data-testid="gamification-widget-content"
          className="flex flex-col gap-3"
        >
          <XpLevelChip
            xpTotal={state.data.xp_total}
            levelTier={state.data.level_tier}
            levelName={state.data.level_name}
            levelProgressPct={state.data.level_progress_pct}
            dailyGoalXp={state.data.daily_goal_xp}
            dailyXpEarned={state.data.daily_xp_earned}
          />
          <StreakChip
            streakDays={state.data.streak_days}
            freezesLeft={state.data.streak_freezes_left}
          />
          <SparseHeatmap tiles={state.data.heatmap} />
        </div>
      )}
    </section>
  );
}
