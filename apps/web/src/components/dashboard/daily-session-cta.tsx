"use client";

/**
 * `<DailySessionCTA>` — the 3-button ADHD entry point to the daily flow
 * (Phase 13 T4, MASTER §8).
 *
 * Sits above `<UrgentReviewsSection>` on the dashboard. Each button
 * fetches a tiny card batch (1 / 5 / 10) from `/sessions/daily-plan`,
 * seeds the Zustand store, and navigates to `/session/daily`.
 *
 * No-guilt semantics
 * ------------------
 * * When the backend returns `reason === "nothing_due"` we swap the
 *   button cluster for a single line: **"Nothing due — great job. Come
 *   back later."** No red badge, no "you should be practicing" nag.
 *   (§8 insists the only two emotional states after this screen are
 *   "let's do one" and "all clear".)
 * * Network or HTTP errors surface inline beneath the buttons; we don't
 *   crash the dashboard. `request()` already toasts via Sonner; we add
 *   a small inline line so keyboard users see the failure next to the
 *   control they pressed.
 *
 * Accessibility
 * -------------
 * * Buttons are `min-h-[44px]` per the mobile touch-target guideline
 *   from §8 (same bar `<QuizOptions>` enforces).
 * * Stacked on narrow viewports, 3-column grid from `sm:` up; fits
 *   inside the dashboard's max-w-6xl column without overflow.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles } from "lucide-react";
import { useT } from "@/lib/i18n-context";
import { getDailyPlan, type DailySessionSize } from "@/lib/api";
import { useDailySessionStore } from "@/store/daily-session";

interface SessionSizeOption {
  size: DailySessionSize;
  label: string;
  subLabel: string;
}

// TODO(i18n): UA дубляж у `locales/uk.json`, поки hardcoded EN per Q3 (§Q3
// dashboard-only audit scope — повний pass по practice-flow screens у Phase 14).
const SIZE_OPTIONS: SessionSizeOption[] = [
  { size: 1, label: "1 card", subLabel: "30 sec" },
  { size: 5, label: "5 cards", subLabel: "3 min" },
  { size: 10, label: "10 cards", subLabel: "5 min" },
];

export function DailySessionCTA() {
  const router = useRouter();
  const t = useT();
  const start = useDailySessionStore((s) => s.start);
  const [pendingSize, setPendingSize] = useState<DailySessionSize | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [emptyReason, setEmptyReason] = useState<string | null>(null);

  const handlePick = async (size: DailySessionSize) => {
    if (pendingSize !== null) return;
    setPendingSize(size);
    setError(null);
    setEmptyReason(null);
    try {
      const plan = await getDailyPlan(size);
      if (plan.cards.length === 0) {
        setEmptyReason(plan.reason ?? "nothing_due");
        setPendingSize(null);
        return;
      }
      start(size, plan.cards);
      router.push("/session/daily");
    } catch (err) {
      setError(
        (err as Error | null)?.message ??
          "Could not start session. Please try again.",
      );
      setPendingSize(null);
    }
  };

  if (emptyReason) {
    return (
      <section
        aria-label={t("dailySession.ariaLabel")}
        data-testid="daily-session-cta"
        className="rounded-2xl bg-card p-5 card-shadow"
      >
        <div className="flex items-start gap-3">
          <Sparkles className="size-5 text-brand shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-sm font-medium text-foreground">
              Nothing due — great job.
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Come back later.
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
      <div className="flex items-center gap-2 mb-3">
        <Sparkles className="size-4 text-brand shrink-0" />
        <h2 className="text-sm font-semibold text-foreground">
          Quick session
        </h2>
      </div>
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
              className="min-h-[44px] rounded-xl bg-muted/40 px-4 py-3 text-left transition-colors hover:bg-muted/60 disabled:opacity-60 disabled:cursor-default"
            >
              <div className="text-sm font-medium text-foreground">
                {pending ? "…" : label}
              </div>
              <div className="text-[11px] text-muted-foreground">
                {pending ? " " : subLabel}
              </div>
            </button>
          );
        })}
      </div>
      {error && (
        <p
          role="alert"
          data-testid="daily-session-cta-error"
          className="mt-2 text-xs text-destructive"
        >
          {error}
        </p>
      )}
    </section>
  );
}
