"use client";

/**
 * `<RoomListItem>` — one row inside `/tracks/[slug]` (Visual Shell V2).
 *
 * V2 promotes the row from "tri-state from raw counts" to "explicit route
 * state" (spec D.5/D.6). The parent computes the route state once via
 * `deriveRoomRouteStates` and passes it down so the rail and the rows
 * stay in sync. When the parent doesn't pass a state we still infer one
 * from the task counts so the component stays usable in isolation
 * (storybook / older callers / single-room previews).
 *
 * Visual mapping (spec D.6 + tokens already used in V1):
 *   done   → emerald-tint chip "Done"
 *   active → amber-tint chip "Active"        + amber border emphasis
 *   ready  → emerald-outline chip "Ready now"
 *   locked → muted/dim chip "Locked" + helper line "Locked until this
 *            mission is done"
 *
 * Each item is a full-card `<Link>` — parent builds the href from the
 * current path slug so we don't thread it through the room summary.
 * Locked rows stay clickable on purpose: the spec is "UI guidance only,
 * do not hard-lock route access" (Part B #6 + Part D doesn't require
 * blocking navigation).
 */

import Link from "next/link";
import { Check, Lock } from "lucide-react";
import type { RoomSummary } from "@/lib/api";
import { ProgressBar } from "./ProgressBar";
import type { RoomRouteState } from "./path-route-state";

/** Truncate to N chars (whitespace-aware) for the intro excerpt.
 *  Backend may already pre-truncate but we defend against longer inputs. */
function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  // Clip at the last whitespace before `max` so we don't mid-word chop
  // for ASCII English. Fallback: hard clip when there's no whitespace.
  const clipped = text.slice(0, max);
  const lastSpace = clipped.lastIndexOf(" ");
  const safe = lastSpace > 40 ? clipped.slice(0, lastSpace) : clipped;
  return `${safe.trimEnd()}…`;
}

interface RoomListItemProps {
  pathSlug: string;
  room: RoomSummary;
  /** Optional explicit route state. When provided it wins over the
   *  count-based fallback below — the parent has more context (sibling
   *  rooms) than this component does in isolation. */
  routeState?: RoomRouteState;
}

/** Backwards-compat fallback for callers that still pass only a single
 *  room. Without sibling context we can only distinguish `done` /
 *  `active` (in-progress) / `ready` (idle, not started). We never emit
 *  `locked` here because there is no anchor room to gate against. */
function inferStateFromCounts(room: RoomSummary): RoomRouteState {
  if (room.task_total > 0 && room.task_complete >= room.task_total) {
    return "done";
  }
  if (room.task_complete > 0 && room.task_total > 0) return "active";
  return "ready";
}

export function RoomListItem({
  pathSlug,
  room,
  routeState,
}: RoomListItemProps) {
  const state: RoomRouteState = routeState ?? inferStateFromCounts(room);

  // Wrapper border / background — emerald for done, amber emphasis for
  // active, default border for ready, muted for locked. We deliberately
  // reuse the V1 token set (no new colors per Part D).
  const wrapperClass =
    state === "done"
      ? "border border-emerald-500/30 bg-emerald-500/5 hover:bg-emerald-500/10"
      : state === "active"
        ? "border border-amber-500/30 bg-card hover:bg-muted/30"
        : state === "locked"
          ? "border border-border bg-muted/20 hover:bg-muted/30 opacity-75"
          : "border border-border bg-card hover:bg-muted/30";

  const fillClass =
    state === "done"
      ? "bg-emerald-500"
      : state === "active"
        ? "bg-amber-500"
        : "bg-primary";

  // `data-state` keeps the V1 contract (`complete` / `in_progress` /
  // `idle`) for any test that already pins on it, while the new
  // `data-route-state` exposes the four-state vocabulary.
  const legacyState =
    state === "done"
      ? "complete"
      : state === "active"
        ? "in_progress"
        : "idle";

  return (
    <Link
      href={`/tracks/${pathSlug}/missions/${room.id}`}
      data-testid={`room-item-${room.id}`}
      data-state={legacyState}
      data-route-state={state}
      className={`block rounded-xl p-4 card-shadow transition-colors ${wrapperClass}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground tabular-nums">
              {String(room.room_order).padStart(2, "0")}
            </span>
            <h3 className="text-sm font-medium text-foreground truncate">
              {room.title}
            </h3>
          </div>
          {room.intro_excerpt && (
            <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
              {truncate(room.intro_excerpt, 160)}
            </p>
          )}
          {state === "locked" && (
            <p
              data-testid={`room-item-locked-helper-${room.id}`}
              className="mt-1 text-[11px] text-muted-foreground"
            >
              Locked until this mission is done
            </p>
          )}
        </div>

        {state === "done" && (
          <span
            data-testid={`room-item-check-${room.id}`}
            className="shrink-0 flex items-center gap-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[11px] font-medium text-emerald-700"
          >
            <Check className="size-3" />
            Done
          </span>
        )}
        {state === "active" && (
          <span
            data-testid={`room-item-chip-${room.id}`}
            className="shrink-0 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-700"
          >
            Active
          </span>
        )}
        {state === "ready" && (
          <span
            data-testid={`room-item-chip-${room.id}`}
            className="shrink-0 rounded-full border border-emerald-500/40 bg-transparent px-2 py-0.5 text-[11px] font-medium text-emerald-700"
          >
            Ready now
          </span>
        )}
        {state === "locked" && (
          <span
            data-testid={`room-item-chip-${room.id}`}
            className="shrink-0 flex items-center gap-1 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11px] font-medium text-muted-foreground"
          >
            <Lock className="size-3" />
            Locked
          </span>
        )}
      </div>

      <div className="mt-3">
        <ProgressBar
          label="Tasks"
          current={room.task_complete}
          total={room.task_total}
          fillClassName={fillClass}
          testId={`room-item-progress-${room.id}`}
        />
      </div>
    </Link>
  );
}
