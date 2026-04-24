"use client";

/**
 * `/tracks/[slug]` — one track with its missions (Phase 16a T4).
 *
 * Server component pattern would force Next 16 to prerender the slug
 * set at build time; since the path set is user-scoped data we use a
 * client-side page with `useParams()` and wrap in Suspense for the
 * build safety check.
 *
 * Data flow
 * ---------
 * Mount → `getPathDetail(slug)` → render `<RoomListItem>` list. No
 * mutation on this screen — clicks route to `/tracks/{slug}/missions/{id}`.
 */

import { Suspense, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { getPathDetail, type PathDetailResponse } from "@/lib/api";
import { RoomListItem } from "@/components/path/RoomListItem";

function PathDetailContent() {
  const params = useParams();
  const slugParam = params?.slug;
  const slug = Array.isArray(slugParam) ? slugParam[0] : slugParam;

  const [data, setData] = useState<PathDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    setLoading(true);
    getPathDetail(slug)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setError(
            err instanceof Error
              ? err.message
              : "Could not load track — try again.",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  return (
    <div className="min-h-screen bg-background py-8 px-4">
      <div className="mx-auto max-w-3xl space-y-6">
        <div>
          <Link
            href="/tracks"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="size-3.5" />
            All tracks
          </Link>
        </div>

        {loading && (
          <div className="space-y-3" data-testid="path-detail-loading">
            <div className="h-8 w-64 rounded bg-muted/40 animate-pulse" />
            <div className="h-4 w-48 rounded bg-muted/40 animate-pulse" />
            <div className="space-y-2 pt-3">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-20 rounded-xl bg-muted/40 animate-pulse"
                />
              ))}
            </div>
          </div>
        )}

        {!loading && error && (
          <div
            role="alert"
            data-testid="path-detail-error"
            className="rounded-2xl bg-destructive/5 px-5 py-4 text-sm text-destructive card-shadow"
          >
            {error}
          </div>
        )}

        {!loading && !error && data && (
          <>
            <div>
              <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
                {data.title}
              </h1>
              {data.description && (
                <p className="mt-2 text-sm text-muted-foreground">
                  {data.description}
                </p>
              )}
              <p
                data-testid="path-detail-summary"
                className="mt-2 text-xs text-muted-foreground"
              >
                {data.room_complete}/{data.room_total} missions cleared
              </p>
            </div>

            <div className="space-y-3" data-testid="path-detail-rooms">
              {data.rooms.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No missions in this track yet.
                </p>
              ) : (
                data.rooms.map((room) => (
                  <RoomListItem
                    key={room.id}
                    pathSlug={data.slug}
                    room={room}
                  />
                ))
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function PathDetailPage() {
  // Wrap in Suspense so `useParams()` doesn't bust Next 16's prerender
  // pass. The inner fallback never renders at runtime (client-side
  // navigation resolves params synchronously) but satisfies the build.
  return (
    <Suspense fallback={<div className="min-h-screen bg-background" />}>
      <PathDetailContent />
    </Suspense>
  );
}
