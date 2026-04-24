"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, Compass, Flag, Timer } from "lucide-react";
import {
  getCurrentMission,
  type CurrentMissionResponse,
} from "@/lib/api/paths";

export function ContinueMissionHero() {
  const [mission, setMission] = useState<CurrentMissionResponse>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    getCurrentMission()
      .then((nextMission) => {
        if (!cancelled) setMission(nextMission);
      })
      .catch(() => {
        if (!cancelled) setMission(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <section
        aria-label="Continue mission"
        data-testid="continue-mission-hero-skeleton"
        className="overflow-hidden rounded-[2rem] border border-border/70 bg-card p-6 card-shadow md:p-8"
      >
        <div className="h-3 w-28 animate-pulse rounded bg-muted/60" />
        <div className="mt-4 h-10 w-72 max-w-full animate-pulse rounded bg-muted/50" />
        <div className="mt-3 h-4 w-full max-w-2xl animate-pulse rounded bg-muted/40" />
        <div className="mt-6 flex flex-wrap gap-2">
          <div className="h-8 w-24 animate-pulse rounded-full bg-muted/40" />
          <div className="h-8 w-20 animate-pulse rounded-full bg-muted/30" />
          <div className="h-8 w-28 animate-pulse rounded-full bg-muted/30" />
        </div>
      </section>
    );
  }

  if (mission === null) {
    return (
      <section
        aria-label="Continue mission"
        data-testid="continue-mission-hero-empty"
        className="overflow-hidden rounded-[2rem] border border-border/70 bg-card p-6 card-shadow md:p-8"
      >
        <div className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-muted/30 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          <Compass className="size-3.5" />
          Mission first
        </div>
        <div className="mt-4 max-w-2xl">
          <h2 className="font-display text-2xl font-semibold tracking-tight text-foreground md:text-4xl">
            Pick your next mission.
          </h2>
          <p className="mt-3 text-sm text-muted-foreground md:text-base">
            Nothing is in progress right now. Browse tracks and start small.
          </p>
        </div>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            href="/tracks"
            data-testid="continue-mission-hero-browse"
            className="inline-flex items-center gap-2 rounded-full bg-brand px-5 py-2.5 text-sm font-medium text-brand-foreground transition-opacity hover:opacity-90"
          >
            Browse tracks
            <ArrowRight className="size-4" />
          </Link>
        </div>
      </section>
    );
  }

  const metaChips = [
    mission.module_label,
    mission.eta_minutes ? `${mission.eta_minutes} min` : null,
    mission.difficulty ? `Difficulty ${mission.difficulty}` : null,
  ].filter(Boolean);

  return (
    <section
      aria-label="Continue mission"
      data-testid="continue-mission-hero"
      className="overflow-hidden rounded-[2rem] border border-brand/20 bg-[radial-gradient(circle_at_top_left,rgba(52,211,153,0.18),transparent_40%),linear-gradient(135deg,rgba(17,24,33,0.95),rgba(11,15,20,0.98))] p-6 card-shadow md:p-8"
    >
      <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-100/80">
            <Flag className="size-3.5" />
            {mission.path_title}
          </div>
          <div className="mt-4">
            <p className="text-sm font-medium text-emerald-100/85">
              Pick up where you left off
            </p>
            <h2
              data-testid="continue-mission-hero-title"
              className="mt-2 font-display text-2xl font-semibold tracking-tight text-white md:text-4xl"
            >
              {mission.title}
            </h2>
            <p className="mt-3 max-w-2xl text-sm text-emerald-50/80 md:text-base">
              {mission.outcome || mission.intro_excerpt || "One mission is enough for today."}
            </p>
          </div>

          {metaChips.length > 0 ? (
            <div className="mt-5 flex flex-wrap gap-2">
              {metaChips.map((chip) => (
                <span
                  key={chip}
                  className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-emerald-50/85"
                >
                  {chip}
                </span>
              ))}
            </div>
          ) : null}
        </div>

        <div className="min-w-[240px] rounded-2xl border border-white/10 bg-black/15 p-4 backdrop-blur-sm">
          <div className="flex items-center justify-between text-xs text-emerald-50/70">
            <span>
              {mission.task_complete}/{mission.task_total} tasks done
            </span>
            <span className="inline-flex items-center gap-1">
              <Timer className="size-3.5" />
              {mission.progress_pct}% through
            </span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
            <div
              data-testid="continue-mission-hero-progress-bar"
              className="h-full rounded-full bg-brand transition-[width] duration-300"
              style={{ width: `${mission.progress_pct}%` }}
            />
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <Link
              href={`/tracks/${mission.path_slug}/missions/${mission.mission_id}`}
              data-testid="continue-mission-hero-open"
              className="inline-flex items-center gap-2 rounded-full bg-brand px-4 py-2 text-sm font-medium text-brand-foreground transition-opacity hover:opacity-90"
            >
              Open mission
              <ArrowRight className="size-4" />
            </Link>
            <Link
              href={`/tracks/${mission.path_slug}`}
              data-testid="continue-mission-hero-track"
              className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-white/85 transition-colors hover:bg-white/10"
            >
              View track
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
