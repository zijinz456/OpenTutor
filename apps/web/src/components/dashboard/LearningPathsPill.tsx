"use client";

/**
 * `<LearningPathsPill>` — compact dashboard entry for the Python learning
 * paths surface (Phase 16a T4 flag F5).
 *
 * Sits directly below `<BrutalDrillCTA>` on the dashboard. Fetches the
 * aggregate path list on mount, sums `room_complete` / `room_total`
 * across all paths, and links out to `/tracks` for the full list.
 *
 * Loading / error
 * ---------------
 * * Loading: a muted skeleton so the card occupies the slot and doesn't
 *   reflow the page when data lands.
 * * Error: a muted single-line fallback ("Could not load paths"). The
 *   shared `request()` already surfaces a toast — we don't double-stack.
 *
 * Orphan caption (flag F2)
 * ------------------------
 * When `orphan_count > 0` we surface it as a small sub-line so the user
 * notices that unmapped content still exists. When the count is zero
 * we omit the line entirely (no "0 orphan cards" visual noise).
 *
 * Panic Mode
 * ----------
 * The root `<section>` carries `data-panic-hide` so `<PanicOverlay>`
 * (Phase 14 T2) collapses this widget alongside the rest of the
 * non-essential dashboard sections when panic mode is enabled.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { GraduationCap } from "lucide-react";
import { listPaths, type PathListResponse } from "@/lib/api";

export function LearningPathsPill() {
  const [data, setData] = useState<PathListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listPaths()
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load paths");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const roomTotal =
    data?.paths.reduce((sum, p) => sum + p.room_total, 0) ?? 0;
  const roomComplete =
    data?.paths.reduce((sum, p) => sum + p.room_complete, 0) ?? 0;
  const orphanCount = data?.orphan_count ?? 0;

  return (
    <section
      aria-label="Learning tracks"
      data-testid="learning-paths-pill"
      data-panic-hide
      className="rounded-2xl border border-emerald-500/30 bg-emerald-500/5 p-5 card-shadow"
    >
      <div className="flex items-start gap-3">
        <GraduationCap className="size-5 shrink-0 text-emerald-600 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground">
            Tracks
          </p>

          {loading && (
            <div
              data-testid="learning-paths-pill-skeleton"
              className="mt-2 h-3 w-40 rounded bg-muted/50 animate-pulse"
            />
          )}

          {!loading && error && (
            <p
              data-testid="learning-paths-pill-error"
              className="mt-1 text-xs text-muted-foreground"
            >
              {error}
            </p>
          )}

          {!loading && !error && data && (
            <>
              <p
                data-testid="learning-paths-pill-progress"
                className="mt-0.5 text-xs text-muted-foreground"
              >
                {roomComplete}/{roomTotal} missions cleared
              </p>
              {orphanCount > 0 && (
                <p
                  data-testid="learning-paths-pill-orphans"
                  className="mt-1 text-[11px] text-muted-foreground/80"
                >
                  {orphanCount} cards not yet mapped
                </p>
              )}
            </>
          )}
        </div>

        <Link
          href="/tracks"
          data-testid="learning-paths-pill-cta"
          className="self-center shrink-0 rounded-full border border-emerald-500/50 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-500/20 transition-colors"
        >
          Browse tracks
        </Link>
      </div>
    </section>
  );
}
