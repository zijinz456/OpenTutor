"use client";

/**
 * `/tracks/[slug]/missions/[missionId]` - mission detail + inline task runner
 * (Phase 16a T4).
 *
 * Pulls the room (with tasks) from the backend on mount, renders an
 * inline task list via `<RoomTaskList>`, and surfaces progress + a
 * back link to the parent path.
 *
 * Suspense
 * --------
 * Wraps the `useParams()`-reading component in Suspense for Next 16's
 * prerender pass (same pattern as `[slug]/page.tsx`).
 */

import { Suspense, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { getRoomDetail, type RoomDetailResponse } from "@/lib/api";
import { RoomTaskList } from "@/components/path/RoomTaskList";

function RoomDetailContent() {
  const params = useParams();
  const slugParam = params?.slug;
  const missionParam = params?.missionId;
  const slug = Array.isArray(slugParam) ? slugParam[0] : slugParam;
  const roomId = Array.isArray(missionParam) ? missionParam[0] : missionParam;

  const [data, setData] = useState<RoomDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** Optimistic overlay on top of the server-returned task_complete. */
  const [bonusComplete, setBonusComplete] = useState(0);

  useEffect(() => {
    if (!slug || !roomId) return;
    let cancelled = false;
    setLoading(true);
    getRoomDetail(slug, roomId)
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setBonusComplete(0);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setError(
            err instanceof Error
              ? err.message
              : "Could not load mission - try again.",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug, roomId]);

  const handleTaskComplete = (taskId: string) => {
    // Only bump for tasks that weren't already green - otherwise the
    // counter would double-count a re-submission of an already-mastered
    // card.
    if (!data) return;
    const task = data.tasks.find((t) => t.id === taskId);
    if (!task || task.is_complete) return;
    setBonusComplete((n) => n + 1);
  };

  const displayedComplete = data
    ? Math.min(data.task_total, data.task_complete + bonusComplete)
    : 0;

  return (
    <div className="min-h-screen bg-background py-8 px-4">
      <div className="mx-auto max-w-3xl space-y-6">
        <div>
          <Link
            href={slug ? `/tracks/${slug}` : "/tracks"}
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="size-3.5" />
            {data ? data.path_title : "Track"}
          </Link>
        </div>

        {loading && (
          <div className="space-y-3" data-testid="room-detail-loading">
            <div className="h-8 w-80 rounded bg-muted/40 animate-pulse" />
            <div className="h-4 w-48 rounded bg-muted/40 animate-pulse" />
            <div className="space-y-2 pt-3">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-16 rounded-xl bg-muted/40 animate-pulse"
                />
              ))}
            </div>
          </div>
        )}

        {!loading && error && (
          <div
            role="alert"
            data-testid="room-detail-error"
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
              {data.intro_excerpt && (
                <p className="mt-2 text-sm text-muted-foreground">
                  {data.intro_excerpt}
                </p>
              )}
              <p
                data-testid="room-detail-progress"
                className="mt-2 text-xs text-muted-foreground"
              >
                {displayedComplete}/{data.task_total} tasks
              </p>
            </div>

            {data.tasks.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No tasks in this mission yet.
                </p>
            ) : (
              <RoomTaskList
                tasks={data.tasks}
                onTaskComplete={handleTaskComplete}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function RoomDetailPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-background" />}>
      <RoomDetailContent />
    </Suspense>
  );
}
