"use client";

/**
 * `<PathCard>` — one cell on `/tracks` (Visual Shell V1).
 *
 * Presentational — parent fetches `listPaths()` and hands one
 * `PathSummary` per card. The whole card is a clickable `<Link>` so a
 * single tap anywhere routes to `/tracks/{slug}`.
 *
 * Layout note (Visual Shell V1)
 * -----------------------------
 * The tracks page now lays cards out in a responsive grid (1/2/3/4
 * columns), so each card needs to be full-height and keep its
 * progress bars pinned to the bottom regardless of description
 * length. We use `h-full flex flex-col` + `mt-auto` on the progress
 * footer so cells in the same row stay visually aligned even when
 * one description wraps to three lines and another wraps to one.
 *
 * Difficulty badge colour
 * -----------------------
 * Matches the dashboard palette used by other track-level widgets:
 * beginner=emerald, intermediate=amber, advanced=red. Unknown
 * difficulty falls back to a neutral muted pill so a future seed that
 * adds a new layer won't render with a broken class.
 */

import Link from "next/link";
import type { PathSummary } from "@/lib/api";
import { ProgressBar } from "./ProgressBar";

const DIFFICULTY_STYLES: Record<string, string> = {
  beginner: "bg-emerald-500/10 text-emerald-700 border-emerald-500/40",
  intermediate: "bg-amber-500/10 text-amber-700 border-amber-500/40",
  advanced: "bg-red-500/10 text-red-700 border-red-500/40",
};

interface PathCardProps {
  summary: PathSummary;
}

export function PathCard({ summary }: PathCardProps) {
  const badgeClass =
    DIFFICULTY_STYLES[summary.difficulty] ??
    "bg-muted/50 text-muted-foreground border-border";

  return (
    <Link
      href={`/tracks/${summary.slug}`}
      data-testid={`path-card-${summary.slug}`}
      className="flex h-full flex-col rounded-2xl border border-border bg-card p-5 card-shadow hover:bg-muted/30 transition-colors"
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-base font-semibold text-foreground">
          {summary.title}
        </h2>
        <span
          data-testid={`path-card-difficulty-${summary.slug}`}
          className={`shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] font-medium capitalize ${badgeClass}`}
        >
          {summary.difficulty}
        </span>
      </div>

      {summary.description && (
        <p className="mt-2 text-sm text-muted-foreground line-clamp-3">
          {summary.description}
        </p>
      )}

      {/* Progress footer pinned to bottom via `mt-auto` — keeps the
          progress bars on a shared baseline across the row even when
          adjacent cards have descriptions of different lengths. */}
      <div className="mt-auto space-y-2 pt-4">
        <ProgressBar
          label="Missions"
          current={summary.room_complete}
          total={summary.room_total}
          testId={`path-card-rooms-${summary.slug}`}
        />
        <ProgressBar
          label="Tasks"
          current={summary.task_complete}
          total={summary.task_total}
          testId={`path-card-tasks-${summary.slug}`}
        />
      </div>
    </Link>
  );
}
