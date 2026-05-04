"use client";

/**
 * `/tracks/[slug]` — one track with its missions (Visual Shell V2).
 *
 * Server component pattern would force Next 16 to prerender the slug
 * set at build time; since the path set is user-scoped data we use a
 * client-side page with `useParams()` and wrap in Suspense for the
 * build safety check.
 *
 * Data flow
 * ---------
 * Mount → `getPathDetail(slug)` → derive route states → render
 * `<RoomListItem>` list with explicit state per row + an enriched rail.
 * No mutation on this screen; clicks route to
 * `/tracks/{slug}/missions/{id}`.
 *
 * Layout note (Visual Shell V1, kept in V2)
 * -----------------------------------------
 * Desktop (xl+) uses an asymmetric grid: a fluid main column for the
 * mission list + a fixed 320px right rail. Below xl the rail collapses
 * below the main column so the mission list stays full-width on
 * tablet/mobile. Mission rows stay a vertical stack — NOT a grid —
 * per spec D.7.
 *
 * V2 additions
 * ------------
 *   - `deriveRoomRouteStates` runs once on the resolved rooms and feeds
 *     both the rail and each row, so they stay in sync.
 *   - The rail gains "Current step", "Next unlocks", and a one-line
 *     route note explaining the learner state (spec Part E).
 *   - All rail data still comes from `getPathDetail` — no new API.
 */

import { Suspense, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { getPathDetail, type PathDetailResponse } from "@/lib/api";
import { RoomListItem } from "@/components/path/RoomListItem";
import { PageShell } from "@/components/layout/page-shell";
import {
  deriveRoomRouteStates,
  findActiveOrReadyRoom,
  findNextLockedRoom,
  type RoomWithRouteState,
} from "@/components/path/path-route-state";
import type { RoomSummary } from "@/lib/api";
import { GenerateRoomCTA } from "@/components/dashboard/generate-room-cta";
import { useCourseStore } from "@/store/course";

const DIFFICULTY_STYLES: Record<string, string> = {
  beginner: "bg-emerald-500/10 text-emerald-700 border-emerald-500/40",
  intermediate: "bg-amber-500/10 text-amber-700 border-amber-500/40",
  advanced: "bg-red-500/10 text-red-700 border-red-500/40",
};

/** One short line summarizing where the learner is in the track. The
 *  copy is operational, not encouraging (spec F.1) — it tells the user
 *  what they are doing and what unlocks next, nothing more. */
function buildRouteNote(
  current: RoomWithRouteState<RoomSummary> | null,
  next: RoomWithRouteState<RoomSummary> | null,
): string {
  if (!current) return "Track complete. Pick another.";
  if (current.route_state === "active") {
    return next
      ? `You are in the middle of ${current.title}. Finish to unlock ${next.title}.`
      : `You are in the middle of ${current.title}.`;
  }
  // current.route_state === "ready"
  return `Ready to start ${current.title}.`;
}

/** Right-rail summary card. Pulls only fields already present on
 *  `PathDetailResponse` — no extra fetches. Hidden visually below xl
 *  via the parent grid (rail collapses below the main column).
 *
 *  V2 adds three derived sections (current step / next unlock / route
 *  note) on top of the V1 static counters. */
function PathSummaryRail({
  data,
  roomStates,
}: {
  data: PathDetailResponse;
  roomStates: RoomWithRouteState<RoomSummary>[];
}) {
  const badgeClass =
    DIFFICULTY_STYLES[data.difficulty] ??
    "bg-muted/50 text-muted-foreground border-border";
  const taskTotal = data.rooms.reduce((sum, r) => sum + r.task_total, 0);
  const taskComplete = data.rooms.reduce(
    (sum, r) => sum + r.task_complete,
    0,
  );

  const current = findActiveOrReadyRoom(roomStates);
  const next = findNextLockedRoom(roomStates);
  const routeNote = buildRouteNote(current, next);

  // Heading copy follows the active/ready distinction so the learner
  // knows whether they are resuming or starting fresh.
  const currentHeading = current
    ? current.route_state === "active"
      ? "Current step"
      : "Start here"
    : "Current step";
  const currentBody = current ? current.title : "Track complete";

  return (
    <div className="rounded-2xl border border-border bg-card p-5 card-shadow space-y-4">
      <div>
        <span
          data-testid="path-detail-rail-difficulty"
          className={`inline-block rounded-full border px-2.5 py-0.5 text-[11px] font-medium capitalize ${badgeClass}`}
        >
          {data.difficulty}
        </span>
        <h2
          data-testid="path-detail-rail-title"
          className="mt-3 text-base font-semibold text-foreground"
        >
          {data.title}
        </h2>
        {data.description && (
          <p
            data-testid="path-detail-rail-description"
            className="mt-2 text-sm text-muted-foreground"
          >
            {data.description}
          </p>
        )}
      </div>

      <div
        data-testid="path-detail-rail-current-step"
        className="border-t border-border pt-4"
      >
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
          {currentHeading}
        </p>
        <p className="mt-1 text-sm font-medium text-foreground">
          {currentBody}
        </p>
      </div>

      {next && (
        <div data-testid="path-detail-rail-next-unlock">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Next unlocks
          </p>
          <p className="mt-1 text-sm text-foreground">{next.title}</p>
        </div>
      )}

      <p
        data-testid="path-detail-rail-route-note"
        className="text-xs text-muted-foreground"
      >
        {routeNote}
      </p>

      <dl className="grid grid-cols-2 gap-3 border-t border-border pt-4">
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Missions
          </dt>
          <dd
            data-testid="path-detail-rail-missions"
            className="mt-1 text-sm font-medium text-foreground tabular-nums"
          >
            {data.room_complete}/{data.room_total}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Tasks
          </dt>
          <dd
            data-testid="path-detail-rail-tasks"
            className="mt-1 text-sm font-medium text-foreground tabular-nums"
          >
            {taskComplete}/{taskTotal}
          </dd>
        </div>
      </dl>
    </div>
  );
}

function PathDetailContent() {
  const params = useParams();
  const slugParam = params?.slug;
  const slug = Array.isArray(slugParam) ? slugParam[0] : slugParam;

  const [data, setData] = useState<PathDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Phase 16b Bundle B v2 — pull the user's courses from the shared
  // course store so we can wire the GenerateRoomCTA. The path-detail
  // payload doesn't expose a course_id mapping, so for MVL we mirror
  // the dashboard heuristic (use courses[0].id) and hide the CTA when
  // no course is available. The store is shared with the dashboard,
  // so by the time the user clicks into a track the data is typically
  // already in the TTL cache — we kick a fetch on mount as a safety
  // net for direct deep-links into /tracks/[slug].
  const courses = useCourseStore((s) => s.courses);
  const fetchCourses = useCourseStore((s) => s.fetchCourses);
  useEffect(() => {
    if (courses.length === 0) {
      void fetchCourses();
    }
    // We deliberately only run this once on mount; the store handles
    // its own cache freshness internally.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const generateCourseId = courses.length > 0 ? courses[0].id : null;

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
              : "Couldn't load track. Retry?",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  // Derive route states once from the resolved room list. Memoizing
  // keeps the same array identity across renders so the rail and rows
  // don't see jitter in their props on unrelated state changes.
  const roomStates = useMemo<RoomWithRouteState<RoomSummary>[]>(
    () => (data ? deriveRoomRouteStates(data.rooms) : []),
    [data],
  );

  return (
    // Visual Shell Phase 1.5 — <PageShell> renders <div>; the page-level
    // <main> landmark is provided by app/layout.tsx.
    <PageShell data-testid="path-detail-shell" className="pb-24 pt-8">
      <header className="mb-8">
        <Link
          href="/tracks"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="size-3.5" />
          All tracks
        </Link>
        {!loading && !error && data && (
          <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
              {data.title}
            </h1>
            {/* Phase 16b Bundle B v2 — track-header GenerateRoomCTA.
                Mounts next to the title so it reads as the primary
                action of this page (vs. the dashboard pill which is
                a secondary nudge). Hidden when no course is in scope
                (P1 — same MVL approach as the dashboard mount). */}
            {generateCourseId ? (
              <div data-testid="track-detail-generate-room-slot">
                <GenerateRoomCTA
                  pathId={data.id}
                  courseId={generateCourseId}
                  pathSlug={data.slug}
                  variant="track-header"
                />
              </div>
            ) : (
              <div data-testid="generate-room-cta-hidden-no-course" />
            )}
          </div>
        )}
      </header>

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
        <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px] gap-8">
          <div data-testid="path-detail-main" className="space-y-3">
            <p
              data-testid="path-detail-summary"
              className="text-xs text-muted-foreground"
            >
              {data.room_complete}/{data.room_total} missions cleared
            </p>
            <div className="space-y-3" data-testid="path-detail-rooms">
              {roomStates.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No missions in this track yet.
                </p>
              ) : (
                roomStates.map((room) => (
                  <RoomListItem
                    key={room.id}
                    pathSlug={data.slug}
                    room={room}
                    routeState={room.route_state}
                  />
                ))
              )}
            </div>
          </div>

          <aside
            data-testid="path-detail-rail"
            className="xl:sticky xl:top-20 xl:self-start space-y-4"
          >
            <PathSummaryRail data={data} roomStates={roomStates} />
          </aside>
        </div>
      )}
    </PageShell>
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
