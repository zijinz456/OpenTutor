"use client";

/**
 * `<RoomListItem>` — one row inside `/tracks/[slug]` (Phase 16a T4).
 *
 * Visual state tri-state from `task_complete` vs `task_total`:
 *   - All green → soft green background + checkmark badge.
 *   - Some progress → amber progress bar (still clickable).
 *   - Nothing started → default muted treatment.
 *
 * Each item is a full-card `<Link>` — parent builds the href from the
 * current path slug so we don't thread it through the room summary.
 */

import Link from "next/link";
import { Check } from "lucide-react";
import type { RoomSummary } from "@/lib/api";
import { ProgressBar } from "./ProgressBar";

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
}

export function RoomListItem({ pathSlug, room }: RoomListItemProps) {
  const complete =
    room.task_total > 0 && room.task_complete >= room.task_total;
  const inProgress =
    !complete && room.task_complete > 0 && room.task_total > 0;

  const wrapperClass = complete
    ? "border border-emerald-500/30 bg-emerald-500/5 hover:bg-emerald-500/10"
    : inProgress
      ? "border border-amber-500/20 bg-card hover:bg-muted/30"
      : "bg-card hover:bg-muted/30";

  const fillClass = complete
    ? "bg-emerald-500"
    : inProgress
      ? "bg-amber-500"
      : "bg-primary";

  const state = complete ? "complete" : inProgress ? "in_progress" : "idle";

  return (
    <Link
      href={`/tracks/${pathSlug}/missions/${room.id}`}
      data-testid={`room-item-${room.id}`}
      data-state={state}
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
        </div>

        {complete && (
          <span
            data-testid={`room-item-check-${room.id}`}
            className="shrink-0 flex items-center gap-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[11px] font-medium text-emerald-700"
          >
            <Check className="size-3" />
            done
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
