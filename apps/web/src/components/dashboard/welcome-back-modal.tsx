"use client";

/**
 * `<WelcomeBackModal>` — ADHD Phase 14 T4 (plan Story 4).
 *
 * Mounted unconditionally on the dashboard, this component fetches
 * `GET /api/sessions/welcome-back` once per mount and renders a radix
 * Dialog when the user has been away long enough and has not already
 * dismissed the reminder today.
 *
 * Gate for showing the modal (ALL must be true):
 *   - `data.gap_days !== null && data.gap_days >= 3`
 *   - `data.last_practice_at !== null`
 *   - `localStorage["ld:welcome-back:dismissed-until"] <= Date.now()`
 *
 * Dismiss semantics
 * -----------------
 * Writing the X, clicking the backdrop, pressing Esc, or clicking any of
 * the three action buttons all dismiss the modal and persist tomorrow's
 * UTC midnight as the next-show threshold. We store ms-since-epoch so
 * parsing stays simple across locales / user-clock quirks.
 *
 * Fail-closed on API errors: if the fetch rejects we never show the
 * modal — the dashboard should not interrupt the user on an API hiccup.
 *
 * Render-once guard: the double-invoke under React Strict Mode / Fast
 * Refresh could otherwise re-fire the fetch and re-show the modal after
 * a dismiss in the same tab. `shownRef` is set true the first time the
 * modal appears; once dismissed, the component returns `null` until the
 * page is reloaded.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useTF, useT } from "@/lib/i18n-context";
import { getWelcomeBack, type WelcomeBackPayload } from "@/lib/api/welcome-back";

const DISMISS_KEY = "ld:welcome-back:dismissed-until";

/** Tomorrow 00:00 UTC in ms since epoch. Uses a cloned Date so we do not
 *  mutate any shared reference. */
function tomorrowUtcMidnightMs(): number {
  const d = new Date();
  d.setUTCHours(24, 0, 0, 0);
  return d.getTime();
}

function isDismissed(): boolean {
  if (typeof window === "undefined") return false;
  const raw = window.localStorage.getItem(DISMISS_KEY);
  if (!raw) return false;
  const until = Number.parseInt(raw, 10);
  if (!Number.isFinite(until)) return false;
  return until > Date.now();
}

function persistDismiss(): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(DISMISS_KEY, String(tomorrowUtcMidnightMs()));
}

/** Pick the gap-day-bucket i18n key. The thresholds come from plan
 *  Story 4 AC #3 (short = 3–7, medium = 8–30, long = 30+). */
function subtitleKey(gapDays: number): string {
  if (gapDays <= 7) return "home.welcomeBack.subtitle.short";
  if (gapDays <= 30) return "home.welcomeBack.subtitle.medium";
  return "home.welcomeBack.subtitle.long";
}

export function WelcomeBackModal() {
  const router = useRouter();
  const t = useT();
  const tf = useTF();
  const [data, setData] = useState<WelcomeBackPayload | null>(null);
  const [open, setOpen] = useState(false);
  const shownRef = useRef(false);

  useEffect(() => {
    if (shownRef.current) return;
    if (isDismissed()) return;

    let cancelled = false;
    (async () => {
      try {
        const payload = await getWelcomeBack();
        if (cancelled) return;
        const eligible =
          payload.gap_days !== null &&
          payload.gap_days >= 3 &&
          payload.last_practice_at !== null;
        if (!eligible) return;
        if (isDismissed()) return;
        shownRef.current = true;
        setData(payload);
        setOpen(true);
      } catch {
        // Fail-closed: never interrupt the user on an API hiccup.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const dismiss = () => {
    persistDismiss();
    setOpen(false);
  };

  const navigate = (href: string) => {
    dismiss();
    router.push(href);
  };

  if (!data || data.gap_days === null) return null;

  const gapDays = data.gap_days;
  const overdue = Math.min(data.overdue_count, 10);
  const overdueSuffix = data.overdue_count > 10 ? "+" : "";
  const hasMastered = data.top_mastered_concepts.length >= 1;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) dismiss();
      }}
    >
      <DialogContent data-testid="welcome-back-modal">
        <DialogHeader>
          <DialogTitle data-testid="welcome-back-title">
            {tf("home.welcomeBack.title", { days: gapDays })}
          </DialogTitle>
          <DialogDescription>{t(subtitleKey(gapDays))}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-2">
          <Button
            type="button"
            variant="default"
            data-testid="welcome-back-one-card"
            onClick={() => navigate("/session/daily?size=1")}
          >
            {t("home.welcomeBack.cta.oneCard")}
          </Button>
          <Button
            type="button"
            variant="outline"
            data-testid="welcome-back-five-cards"
            onClick={() => navigate("/session/daily?size=5")}
          >
            {t("home.welcomeBack.cta.fiveCards")}
          </Button>
          {hasMastered && (
            <Button
              type="button"
              variant="outline"
              data-testid="welcome-back-review"
              onClick={() =>
                navigate(
                  `/recap?concepts=${encodeURIComponent(
                    data.top_mastered_concepts.join("|"),
                  )}`,
                )
              }
            >
              {t("home.welcomeBack.cta.review")}
            </Button>
          )}
        </div>

        <DialogFooter>
          <p
            data-testid="welcome-back-overdue"
            className="text-xs text-muted-foreground"
          >
            {tf("home.welcomeBack.overdue", {
              count: `${overdue}${overdueSuffix}`,
            })}
          </p>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
