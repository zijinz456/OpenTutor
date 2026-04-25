"use client";

/**
 * `<DailySessionCTA>` is the 3-button ADHD entry point to the daily flow.
 *
 * Sits above `<UrgentReviewsSection>` on the dashboard. Each button
 * fetches a tiny card batch (1 / 5 / 10) from `/sessions/daily-plan`,
 * seeds the Zustand store, and navigates to `/session/daily`.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles } from "lucide-react";
import { getDailyPlan, type DailySessionSize } from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { useBadDayStore } from "@/store/bad-day";
import { useDailySessionStore } from "@/store/daily-session";

interface SessionSizeOption {
  size: DailySessionSize;
  label: string;
  subLabel: string;
}

const SIZE_OPTIONS: SessionSizeOption[] = [
  { size: 1, label: "One card", subLabel: "30 sec" },
  { size: 5, label: "Five cards", subLabel: "3 min" },
  { size: 10, label: "Ten cards", subLabel: "5 min" },
];

export function DailySessionCTA() {
  const router = useRouter();
  const t = useT();
  const start = useDailySessionStore((s) => s.start);
  const badDayActive = useBadDayStore((s) => s.isActiveToday());
  const [pendingSize, setPendingSize] = useState<DailySessionSize | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [emptyReason, setEmptyReason] = useState<string | null>(null);

  const handlePick = async (size: DailySessionSize) => {
    if (pendingSize !== null) return;

    setPendingSize(size);
    setError(null);
    setEmptyReason(null);

    try {
      const plan = badDayActive
        ? await getDailyPlan(size, { strategy: "easy_only" })
        : await getDailyPlan(size);

      if (plan.cards.length === 0) {
        setEmptyReason(plan.reason ?? "nothing_due");
        setPendingSize(null);
        return;
      }

      start(size, plan.cards);
      router.push(
        badDayActive ? "/session/daily?strategy=easy_only" : "/session/daily",
      );
    } catch (err) {
      setError(
        (err as Error | null)?.message ??
          "Couldn't start session. Retry?",
      );
      setPendingSize(null);
    }
  };

  if (emptyReason) {
    const badDayEmpty = emptyReason === "bad_day_empty";

    return (
      <section
        aria-label={t("dailySession.ariaLabel")}
        data-testid="daily-session-cta"
        className="rounded-2xl bg-card p-5 card-shadow"
      >
        <div className="flex items-start gap-3">
          <Sparkles className="mt-0.5 size-5 shrink-0 text-brand" />
          <div className="flex-1">
            <p className="text-sm font-medium text-foreground">
              {badDayEmpty
                ? "Nothing easy due today."
                : "Nothing due today. Come back tomorrow."}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {badDayEmpty
                ? "Turn off Easy mode or come back tomorrow."
                : "No guilt necessary."}
            </p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section
      aria-label={t("dailySession.ariaLabel")}
      data-testid="daily-session-cta"
      className="rounded-2xl bg-card p-5 card-shadow"
    >
      <div className="mb-3 flex items-center gap-2">
        <Sparkles className="size-4 shrink-0 text-brand" />
        <h2 className="text-sm font-semibold text-foreground">Quick session</h2>
      </div>
      {badDayActive ? (
        <div
          data-testid="daily-session-cta-bad-day-chip"
          className="mb-3 inline-flex rounded-full bg-brand-muted px-3 py-1 text-xs font-medium text-brand"
        >
          {t("home.badDay.ctaChip")}
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {SIZE_OPTIONS.map(({ size, label, subLabel }) => {
          const pending = pendingSize === size;
          const disabled = pendingSize !== null;

          return (
            <button
              key={size}
              type="button"
              disabled={disabled}
              onClick={() => void handlePick(size)}
              data-testid={`daily-session-cta-${size}`}
              aria-busy={pending}
              className="min-h-[44px] rounded-xl bg-muted/40 px-4 py-3 text-left transition-colors hover:bg-muted/60 disabled:cursor-default disabled:opacity-60"
            >
              <div className="text-sm font-medium text-foreground">
                {pending ? "..." : label}
              </div>
              <div className="text-[11px] text-muted-foreground">
                {pending ? " " : subLabel}
              </div>
            </button>
          );
        })}
      </div>
      {error ? (
        <p
          role="alert"
          data-testid="daily-session-cta-error"
          className="mt-2 text-xs text-destructive"
        >
          {error}
        </p>
      ) : null}
    </section>
  );
}
