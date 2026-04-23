"use client";

/**
 * `<BrutalDrillCTA>` — dashboard entry point to the Brutal Drill runner
 * (Phase 6 T4).
 *
 * Sits directly below `<DailySessionCTA>` on the dashboard. Click →
 * (first-time only) onboarding modal → size × timeout picker → route
 * `/session/brutal?size=N&timeout=Xs`.
 *
 * Flow
 * ----
 * 1. First click ever: show onboarding modal. Copy is deliberately stark
 *    ("Focused Mode, not soft-mode...") so the user understands the
 *    no-skip / no-pause contract before opting in. "Don't show again"
 *    checkbox writes `brutal_onboarding_seen=true` to localStorage.
 * 2. Subsequent clicks: skip onboarding, open picker directly.
 * 3. The dashboard CTA also honours `?open_brutal=true` — the closure
 *    screen's "Run another Brutal" button redirects with that param so
 *    the picker auto-opens without forcing a dashboard click.
 *
 * Styling posture
 * ---------------
 * Amber/yellow (Tailwind `amber-500` border + soft amber background),
 * NOT destructive red. The visual contract (plan §Architecture → CTA)
 * is "secondary below daily, not alarming" — red would read as error.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Flame } from "lucide-react";
import type {
  BrutalSessionSize,
  BrutalTimeoutSeconds,
} from "@/lib/api";

const ONBOARDING_LS_KEY = "brutal_onboarding_seen";

const SIZES: BrutalSessionSize[] = [20, 30, 50];
const TIMEOUTS: BrutalTimeoutSeconds[] = [15, 30, 60];

/** Narrow localStorage access so SSR / tests that lack `window` don't
 *  throw on mount. The CTA is a client component (`"use client"`) but
 *  Next renders it server-side during initial HTML; Vitest runs under
 *  jsdom where `window` exists, so this is mostly a belt-and-braces
 *  guard. */
function readOnboardingSeen(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(ONBOARDING_LS_KEY) === "true";
  } catch {
    return false;
  }
}

function writeOnboardingSeen(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ONBOARDING_LS_KEY, "true");
  } catch {
    // localStorage can throw in private-browsing / quota-exceeded scenarios.
    // Swallow — the worst case is the onboarding shows again next time,
    // which is strictly better than crashing the dashboard.
  }
}

export function BrutalDrillCTA() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const [dontShowAgain, setDontShowAgain] = useState(true);
  const [size, setSize] = useState<BrutalSessionSize>(30);
  const [timeout, setTimeoutSec] =
    useState<BrutalTimeoutSeconds>(30);

  // Honour `?open_brutal=true` from the closure's "Run another" action.
  // The effect runs once per mount — the closure navigates with
  // `router.push` which unmounts the runner and mounts the dashboard,
  // so we won't miss the signal.
  useEffect(() => {
    if (searchParams?.get("open_brutal") === "true") {
      if (readOnboardingSeen()) {
        setShowPicker(true);
      } else {
        setShowOnboarding(true);
      }
    }
  }, [searchParams]);

  const handleCtaClick = useCallback(() => {
    if (readOnboardingSeen()) {
      setShowPicker(true);
    } else {
      setShowOnboarding(true);
    }
  }, []);

  const handleOnboardingContinue = useCallback(() => {
    if (dontShowAgain) writeOnboardingSeen();
    setShowOnboarding(false);
    setShowPicker(true);
  }, [dontShowAgain]);

  const handleStart = useCallback(() => {
    setShowPicker(false);
    router.push(`/session/brutal?size=${size}&timeout=${timeout}`);
  }, [router, size, timeout]);

  return (
    <>
      <section
        aria-label="Brutal Drill"
        data-testid="brutal-drill-cta"
        className="rounded-2xl border border-amber-500/40 bg-amber-500/5 p-5 card-shadow"
      >
        <button
          type="button"
          onClick={handleCtaClick}
          data-testid="brutal-drill-cta-button"
          className="flex w-full items-start gap-3 text-left"
        >
          <Flame className="size-5 shrink-0 text-amber-600 mt-0.5" />
          <div className="flex-1">
            <p className="text-sm font-semibold text-foreground">
              Brutal Drill
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              For interview prep nights.
            </p>
          </div>
        </button>
      </section>

      {showOnboarding ? (
        <OnboardingModal
          dontShowAgain={dontShowAgain}
          onDontShowAgainChange={setDontShowAgain}
          onContinue={handleOnboardingContinue}
          onCancel={() => setShowOnboarding(false)}
        />
      ) : null}

      {showPicker ? (
        <PickerModal
          size={size}
          timeout={timeout}
          onSizeChange={setSize}
          onTimeoutChange={setTimeoutSec}
          onStart={handleStart}
          onCancel={() => setShowPicker(false)}
        />
      ) : null}
    </>
  );
}

/** Onboarding copy is load-bearing — the stark framing IS the feature.
 *  Extracting to a component keeps the CTA's flow logic readable. */
function OnboardingModal({
  dontShowAgain,
  onDontShowAgainChange,
  onContinue,
  onCancel,
}: {
  dontShowAgain: boolean;
  onDontShowAgainChange: (v: boolean) => void;
  onContinue: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Brutal Drill onboarding"
      data-testid="brutal-drill-onboarding"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-sm space-y-4 rounded-2xl bg-card p-6 card-shadow"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-foreground">
          Focused Mode, not soft-mode
        </h2>
        <p className="text-sm text-muted-foreground leading-relaxed">
          No skip. No pause. Wrong answers come back. This is the mode for
          the night before an interview.
        </p>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={dontShowAgain}
            onChange={(e) => onDontShowAgainChange(e.target.checked)}
            data-testid="brutal-drill-onboarding-dontshow"
            className="size-4 rounded border-border"
          />
          Don&apos;t show again
        </label>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onCancel}
            data-testid="brutal-drill-onboarding-cancel"
            className="flex-1 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onContinue}
            data-testid="brutal-drill-onboarding-continue"
            className="flex-1 rounded-lg bg-amber-600 px-3 py-2 text-sm font-medium text-white hover:bg-amber-600/90 transition-colors"
          >
            Continue
          </button>
        </div>
      </div>
    </div>
  );
}

/** 3×3 radio grid: size (20/30/50) × timeout (15/30/60s). Kept simple
 *  buttons instead of `<input type="radio">` — each axis has its own
 *  data-testid so tests can click by value without worrying about role
 *  grouping semantics. */
function PickerModal({
  size,
  timeout,
  onSizeChange,
  onTimeoutChange,
  onStart,
  onCancel,
}: {
  size: BrutalSessionSize;
  timeout: BrutalTimeoutSeconds;
  onSizeChange: (v: BrutalSessionSize) => void;
  onTimeoutChange: (v: BrutalTimeoutSeconds) => void;
  onStart: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Brutal Drill picker"
      data-testid="brutal-drill-picker"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-sm space-y-5 rounded-2xl bg-card p-6 card-shadow"
        onClick={(e) => e.stopPropagation()}
      >
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            Cards
          </p>
          <div className="grid grid-cols-3 gap-2">
            {SIZES.map((n) => {
              const selected = n === size;
              return (
                <button
                  key={n}
                  type="button"
                  onClick={() => onSizeChange(n)}
                  data-testid={`brutal-drill-size-${n}`}
                  aria-pressed={selected}
                  className={`min-h-[44px] rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                    selected
                      ? "border-amber-500 bg-amber-500/10 text-foreground"
                      : "border-border text-muted-foreground hover:border-amber-500/50"
                  }`}
                >
                  {n}
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            Timeout
          </p>
          <div className="grid grid-cols-3 gap-2">
            {TIMEOUTS.map((t) => {
              const selected = t === timeout;
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => onTimeoutChange(t)}
                  data-testid={`brutal-drill-timeout-${t}`}
                  aria-pressed={selected}
                  className={`min-h-[44px] rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                    selected
                      ? "border-amber-500 bg-amber-500/10 text-foreground"
                      : "border-border text-muted-foreground hover:border-amber-500/50"
                  }`}
                >
                  {t}s
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            onClick={onCancel}
            data-testid="brutal-drill-picker-cancel"
            className="flex-1 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onStart}
            data-testid="brutal-drill-picker-start"
            className="flex-1 rounded-lg bg-amber-600 px-3 py-2 text-sm font-medium text-white hover:bg-amber-600/90 transition-colors"
          >
            Start
          </button>
        </div>
      </div>
    </div>
  );
}
