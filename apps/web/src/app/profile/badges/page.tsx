"use client";

/**
 * `/profile/badges` — full badge catalog page
 * (Phase 16c Bundle C — Subagent B).
 *
 * Two stacked sections: "Unlocked" (full tile + unlock_at date) and
 * "Locked" (muted tile + hint shown). Layout uses the Visual Shell V1
 * outer scaffold (`max-w-[1600px]` + responsive horizontal padding +
 * generous bottom space) so the page reads as part of the gamification
 * surface rather than a standalone modal.
 *
 * Calm by design: no confetti, no celebration animation. Locked tiles
 * deliberately surface the `hint` so users know what to chase next
 * without the hint landing as a deficit-framed nag.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { clsx } from "clsx";
import {
  getBadges,
  type BadgeOut,
  type BadgesResponse,
} from "@/lib/api/gamification";

/** Same icon table as `<BadgeShelf>` — kept local to avoid a shared util. */
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

/** Render an ISO datetime as a short `YYYY-MM-DD` string; null falls back. */
function formatUnlockedAt(iso: string | null): string | null {
  if (!iso) return null;
  // Backend returns ISO-8601 UTC. Trim to date for the "calm collectible"
  // aesthetic — the hour/minute precision is noise on a catalog page.
  const dateMatch = iso.match(/^(\d{4}-\d{2}-\d{2})/);
  return dateMatch?.[1] ?? iso;
}

interface FullBadgeTileProps {
  badge: BadgeOut;
}

function FullBadgeTile({ badge }: FullBadgeTileProps) {
  const unlocked = badge.unlocked;
  const unlockedDate = formatUnlockedAt(badge.unlocked_at);
  return (
    <div
      data-testid={`profile-badges-tile-${badge.key}`}
      data-unlocked={unlocked ? "true" : "false"}
      className={clsx(
        "flex gap-3 rounded-2xl border p-4",
        unlocked
          ? "border-border bg-emerald-500/20 text-foreground"
          : "border-border bg-card text-muted-foreground opacity-70",
      )}
    >
      <span aria-hidden="true" className="text-3xl leading-none">
        {badgeIcon(badge.key)}
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold">{badge.title}</p>
        <p className="mt-1 text-xs">{badge.description}</p>
        {unlocked ? (
          unlockedDate && (
            <p className="mt-2 text-xs text-muted-foreground tabular-nums">
              Unlocked {unlockedDate}
            </p>
          )
        ) : (
          <p className="mt-2 text-xs text-muted-foreground">
            Hint: {badge.hint}
          </p>
        )}
      </div>
    </div>
  );
}

export default function ProfileBadgesPage() {
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

  return (
    <div
      data-testid="profile-badges-page"
      className="mx-auto w-full max-w-[1600px] px-4 md:px-6 xl:px-10 pb-24"
    >
      <div className="pt-8">
        <Link
          href="/"
          data-testid="profile-badges-back"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="size-3.5" />
          Dashboard
        </Link>
        <h1 className="font-display mt-2 text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
          All badges
        </h1>
      </div>

      {loading && (
        <div
          data-testid="profile-badges-loading"
          className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-2"
        >
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-24 rounded-2xl bg-muted/40 animate-pulse"
            />
          ))}
        </div>
      )}

      {!loading && error && (
        <div
          role="alert"
          data-testid="profile-badges-error"
          className="mt-6 rounded-2xl border border-border bg-card p-4 text-sm text-muted-foreground"
        >
          <p>{error}</p>
          <button
            type="button"
            onClick={load}
            className="mt-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-foreground hover:bg-emerald-500/20 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && data && (
        <>
          <section
            data-testid="profile-badges-unlocked"
            aria-label="Unlocked badges"
            className="mt-8"
          >
            <div className="flex items-baseline justify-between gap-3">
              <h2 className="text-base font-semibold text-foreground">
                Unlocked
              </h2>
              <span
                data-testid="profile-badges-unlocked-count"
                className="text-xs text-muted-foreground tabular-nums"
              >
                {unlocked.length}
              </span>
            </div>
            {unlocked.length === 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">
                No badges yet. Keep learning.
              </p>
            ) : (
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                {unlocked.map((badge) => (
                  <FullBadgeTile key={badge.key} badge={badge} />
                ))}
              </div>
            )}
          </section>

          <section
            data-testid="profile-badges-locked"
            aria-label="Locked badges"
            className="mt-8"
          >
            <div className="flex items-baseline justify-between gap-3">
              <h2 className="text-base font-semibold text-foreground">
                Locked
              </h2>
              <span
                data-testid="profile-badges-locked-count"
                className="text-xs text-muted-foreground tabular-nums"
              >
                {locked.length}
              </span>
            </div>
            {locked.length === 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">
                Everything unlocked. Nice run.
              </p>
            ) : (
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                {locked.map((badge) => (
                  <FullBadgeTile key={badge.key} badge={badge} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
