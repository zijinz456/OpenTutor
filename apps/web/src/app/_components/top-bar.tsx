"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { PageShell } from "@/components/layout/page-shell";
import { TodayToolsPopover } from "@/components/shared/today-tools-popover";
import { getGamificationDashboard } from "@/lib/api/gamification";

const NAV_ITEMS = [
  { href: "/tracks", label: "Tracks" },
  { href: "/session/daily", label: "Review" },
  { href: "/recap", label: "Recap" },
];

// Chip mirrors the passive-status posture of <GamificationWidget>:
// loading shows an em-dash placeholder (NOT "🔥 0", which would lie),
// error keeps the chip rendered with the same placeholder so the layout
// doesn't shift, and `streak_days = 0` is rendered honestly. We hit
// the same `/api/gamification/dashboard` the widget already polls, so
// the value matches what Юрій sees on the dashboard streak card.
type StreakState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; streakDays: number };

export function TopBar() {
  const pathname = usePathname();
  const [streak, setStreak] = useState<StreakState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    getGamificationDashboard()
      .then((data) => {
        if (!cancelled) {
          setStreak({ status: "loaded", streakDays: data.streak_days });
        }
      })
      .catch(() => {
        if (!cancelled) setStreak({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const streakLabel =
    streak.status === "loaded" ? `🔥 ${streak.streakDays}` : "🔥 —";

  return (
    <header className="fixed inset-x-0 top-0 z-40 border-b border-border/80 bg-background/92 backdrop-blur">
      {/* Visual Shell Phase 1.5 — inner wrapper uses <PageShell> so the
          TopBar's right edge lines up with the page content beneath it
          at any viewport. Previously capped at `max-w-7xl` (1280px),
          which inset the streak chip/nav ~160px left of the page on
          ≥1440px monitors. */}
      <PageShell className="flex h-12 items-center justify-between gap-4">
        <Link
          href="/"
          className="font-display shrink-0 text-base font-semibold tracking-tight text-foreground"
        >
          LearnDopamine
        </Link>

        <nav className="hidden items-center gap-2 md:flex">
          {NAV_ITEMS.map((item) => {
            const active =
              pathname === item.href ||
              (item.href === "/tracks" && pathname?.startsWith("/tracks"));
            return (
              <Link
                key={item.href}
                href={item.href}
                data-testid={`top-bar-link-${item.label.toLowerCase()}`}
                className={cn(
                  "rounded-full px-3 py-1 text-sm font-medium transition-colors",
                  active
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-muted/70 hover:text-foreground",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="flex items-center gap-2">
          <TodayToolsPopover />
          <span
            data-testid="top-bar-streak-chip"
            data-streak-status={streak.status}
            aria-busy={streak.status === "loading"}
            className="inline-flex h-9 items-center rounded-full border border-border/80 bg-card/80 px-3 text-sm font-medium text-foreground"
          >
            {streakLabel}
          </span>
        </div>
      </PageShell>
    </header>
  );
}
