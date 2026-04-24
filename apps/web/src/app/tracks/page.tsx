"use client";

/**
 * `/tracks` — track list (Phase 16a T4).
 *
 * Lists every `LearningPath` the backend returns from `GET /api/paths`,
 * ordered by `track_id` ascending (fundamentals → intermediate →
 * advanced → practical). Each entry is a `<PathCard>` that links to
 * `/tracks/{slug}`.
 *
 * Data shape note
 * ---------------
 * The API doesn't guarantee `track_id` ordering — the backend currently
 * returns by `created_at`, which matches `track_id` in the P0 seed but
 * could drift. We sort client-side to keep the UI contract stable
 * regardless of seed order.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { listPaths, type PathListResponse } from "@/lib/api";
import { PathCard } from "@/components/path/PathCard";

/** Canonical track order for the paths list UI. Any track_id not in
 *  this map sorts to the end but stays alphabetical within "other". */
const TRACK_ORDER: Record<string, number> = {
  fundamentals: 0,
  intermediate: 1,
  advanced: 2,
  practical: 3,
};

export default function PathListPage() {
  const [data, setData] = useState<PathListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listPaths()
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setError(
            err instanceof Error
              ? err.message
              : "Could not load paths — try again.",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const sortedPaths = data
    ? [...data.paths].sort((a, b) => {
        const ao = TRACK_ORDER[a.track_id] ?? 99;
        const bo = TRACK_ORDER[b.track_id] ?? 99;
        if (ao !== bo) return ao - bo;
        return a.title.localeCompare(b.title);
      })
    : [];

  const orphanCount = data?.orphan_count ?? 0;

  return (
    <div className="min-h-screen bg-background py-8 px-4">
      <div className="mx-auto max-w-3xl space-y-6">
        <div>
          <Link
            href="/"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="size-3.5" />
            Home
          </Link>
          <h1 className="font-display mt-2 text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
            Tracks
          </h1>
          {orphanCount > 0 && (
            <p
              data-testid="path-list-orphan-caption"
              className="mt-1 text-xs text-muted-foreground"
            >
              {orphanCount} cards not yet in a track
            </p>
          )}
        </div>

        {loading && (
          <div className="space-y-3" data-testid="path-list-loading">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-28 rounded-2xl bg-muted/40 animate-pulse"
              />
            ))}
          </div>
        )}

        {!loading && error && (
          <div
            role="alert"
            data-testid="path-list-error"
            className="rounded-2xl bg-destructive/5 px-5 py-4 text-sm text-destructive card-shadow"
          >
            {error}
          </div>
        )}

        {!loading && !error && data && (
          <div className="space-y-3" data-testid="path-list">
            {sortedPaths.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No tracks yet.
              </p>
            ) : (
              sortedPaths.map((summary) => (
                <PathCard key={summary.id} summary={summary} />
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
