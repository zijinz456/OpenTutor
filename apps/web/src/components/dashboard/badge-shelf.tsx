"use client";

/**
 * `<BadgeShelf>` — compact badge collectible shelf
 * (Phase 16c Bundle C — Subagent B).
 *
 * Renders the learner's badges as a calm grid: unlocked tiles are tinted
 * in ``bg-emerald-500/20`` and muted-locked tiles are dim. ADHD §11
 * applies: NO confetti, NO sound, NO bouncing animation — just a
 * "collectible feel". Emoji icons per key (one per canonical badge from
 * spec A.2) keep the visual hook without adding a dependency.
 *
 * The shelf fetches its own data on mount and stays self-contained so
 * the dashboard host only has to drop `<BadgeShelf />` next to the other
 * gamification cards. Errors render inline with a retry button — never a
 * global toast — to match the `gamification-widget` posture.
 *
 * A "Show all" link appears once the shelf clips at `MAX_VISIBLE` so the
 * full catalog is reachable from `/profile/badges`.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { clsx } from "clsx";
import {
  getBadges,
  type BadgeOut,
  type BadgesResponse,
} from "@/lib/api/gamification";

const MAX_VISIBLE = 8;

/**
 * Map a canonical badge key (spec A.2) to a single emoji glyph. Unknown
 * keys fall back to a generic star — the backend may add new keys before
 * we ship a matching tile here.
 */
function badgeIcon(key: string): string {
  switch (key) {
    case "first_card":
      return "🌱";
    case "first_room_completed":
      return "🚪";
    case "7_day_streak":
      return "🔥";
    case "30_day_streak":
      return "🏔️";
    case "100_xp":
      return "✨";
    case "1000_xp":
      return "💎";
    case "python_fluent":
      return "🐍";
    case "hacker_novice":
      return "🛡️";
    case "no_hint_hero":
      return "🎯";
    case "comeback_kid":
      return "🌅";
    default:
      return "★";
  }
}

interface BadgeTileProps {
  badge: BadgeOut;
}

/** Single tile — colored when unlocked, muted when locked. */
function BadgeTile({ badge }: BadgeTileProps) {
  const unlocked = badge.unlocked;
  return (
    <div
      data-testid={`badge-tile-${badge.key}`}
      data-unlocked={unlocked ? "true" : "false"}
      title={badge.hint}
      className={clsx(
        "flex flex-col items-center gap-1 rounded-xl border p-3 text-center",
        unlocked
          ? "border-border bg-emerald-500/20 text-foreground"
          : "border-border bg-card text-muted-foreground opacity-60",
      )}
    >
      <span aria-hidden="true" className="text-2xl leading-none">
        {badgeIcon(badge.key)}
      </span>
      <span className="text-xs font-medium leading-tight">{badge.title}</span>
    </div>
  );
}

export function BadgeShelf() {
  const [data, setData] = useState<BadgesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    let cancelled = false;
    getBadges()
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load badges. Refresh to retry.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const cancel = load();
    return cancel;
  }, [load]);

  const unlocked = data?.unlocked ?? [];
  const locked = data?.locked ?? [];
  const total = unlocked.length + locked.length;

  // Show unlocked first, then fill with locked previews up to MAX_VISIBLE.
  const visible: BadgeOut[] = [...unlocked, ...locked].slice(0, MAX_VISIBLE);
  const hasMore = total > visible.length;

  return (
    <section
      data-testid="badge-shelf"
      aria-label="Badges"
      className="rounded-2xl border border-border bg-card p-5 card-shadow"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-foreground">Badges</h2>
        {!loading && !error && data && (
          <span
            data-testid="badge-shelf-caption"
            className="text-xs text-muted-foreground tabular-nums"
          >
            {unlocked.length} of {total} unlocked
          </span>
        )}
      </div>

      {loading && (
        <div
          data-testid="badge-shelf-skeleton"
          className="mt-4 grid grid-cols-4 gap-2"
        >
          {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
            <div
              key={i}
              className="h-20 rounded-xl bg-muted/40 animate-pulse"
            />
          ))}
        </div>
      )}

      {!loading && error && (
        <div
          role="alert"
          data-testid="badge-shelf-error"
          className="mt-3 rounded-xl border border-border bg-card p-3 text-xs text-muted-foreground"
        >
          <p>{error}</p>
          <button
            type="button"
            data-testid="badge-shelf-retry"
            onClick={load}
            className="mt-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-foreground hover:bg-emerald-500/20 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && data && total === 0 && (
        <p
          data-testid="badge-shelf-empty"
          className="mt-3 text-xs text-muted-foreground"
        >
          No badges yet. Keep learning.
        </p>
      )}

      {!loading && !error && data && total > 0 && unlocked.length === 0 && (
        <p
          data-testid="badge-shelf-empty"
          className="mt-3 text-xs text-muted-foreground"
        >
          No badges yet. Keep learning.
        </p>
      )}

      {!loading && !error && data && visible.length > 0 && (
        <div
          data-testid="badge-shelf-grid"
          className="mt-4 grid grid-cols-4 gap-2"
        >
          {visible.map((badge) => (
            <BadgeTile key={badge.key} badge={badge} />
          ))}
        </div>
      )}

      {!loading && !error && data && hasMore && (
        <Link
          href="/profile/badges"
          data-testid="badge-shelf-show-all"
          className="mt-3 inline-block text-xs font-medium text-foreground hover:text-emerald-500 transition-colors"
        >
          Show all
        </Link>
      )}
    </section>
  );
}
