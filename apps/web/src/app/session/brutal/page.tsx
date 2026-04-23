"use client";

/**
 * `/session/brutal` — the Brutal Drill runner (Phase 6 T3).
 *
 * Reads config from query string (`size`, `timeout`), fetches the
 * struggle-first batch from `GET /api/sessions/brutal-plan`, seeds the
 * `brutal-session` Zustand store, and drives the no-skip / no-pause
 * runner until every card has been answered correctly (or hit the
 * 10-attempt force-retire cap).
 *
 * Renderer — MC only for P0
 * -------------------------
 * Backend filters out code / lab cards from brutal batches (plan
 * §Architecture "MC-only P0"), so we don't bother with the dispatch
 * this page's daily sibling runs. A non-MC card is treated as a data
 * contract violation — we log and force-retire it via a wrong-answer
 * submit so the user doesn't get stuck.
 *
 * Timer ring
 * ----------
 * `<BrutalTimerRing>` is keyed by `${cardId}-${attempts[cardId] ?? 0}`
 * so it remounts on every new card AND every retry of the same card.
 * The page owns `visibilitychange` → `paused` so tab-blur doesn't
 * auto-fail the user.
 *
 * Confirm modals
 * --------------
 * * `warning === "pool_small"` → confirm "Only N cards available —
 *   drill anyway?"; Yes starts, No routes home.
 * * Empty cards (nothing_due equivalent) → closure screen with 0/0/0.
 *
 * Exit = bare back button, no confirmation (plan §P0.5).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Flame } from "lucide-react";
import {
  getBrutalPlan,
  submitAnswer,
  type AnswerResult,
  type BrutalPlanResponse,
  type BrutalSessionSize,
  type BrutalTimeoutSeconds,
} from "@/lib/api";
import {
  useBrutalSessionStore,
  type BrutalTimeoutMs,
} from "@/store/brutal-session";
import { QuizOptions } from "@/components/sections/practice/quiz-options";
import { BrutalTimerRing } from "@/components/session/brutal-timer-ring";
import { BrutalClosure } from "@/components/session/brutal-closure";

const BRUTAL_TIMEOUT_SENTINEL = "__brutal_timeout__";

const ALLOWED_SIZES: ReadonlySet<number> = new Set([20, 30, 50]);
const ALLOWED_TIMEOUTS: ReadonlySet<number> = new Set([15, 30, 60]);

/** Parse + validate search params. Returns `null` if either axis is
 *  missing / malformed — the page redirects to `/` in that case. */
function parseConfig(
  search: URLSearchParams | null,
): { size: BrutalSessionSize; timeoutSec: BrutalTimeoutSeconds } | null {
  if (!search) return null;
  const sizeRaw = Number(search.get("size"));
  const timeoutRaw = Number(search.get("timeout"));
  if (!ALLOWED_SIZES.has(sizeRaw) || !ALLOWED_TIMEOUTS.has(timeoutRaw)) {
    return null;
  }
  return {
    size: sizeRaw as BrutalSessionSize,
    timeoutSec: timeoutRaw as BrutalTimeoutSeconds,
  };
}

export default function BrutalSessionPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const queue = useBrutalSessionStore((s) => s.queue);
  const mastered = useBrutalSessionStore((s) => s.mastered);
  const attempts = useBrutalSessionStore((s) => s.attempts);
  const maxStreak = useBrutalSessionStore((s) => s.maxStreak);
  const currentStreak = useBrutalSessionStore((s) => s.currentStreak);
  const forceRetired = useBrutalSessionStore((s) => s.forceRetired);
  const conceptFailTally = useBrutalSessionStore((s) => s.conceptFailTally);
  const startedAt = useBrutalSessionStore((s) => s.startedAt);
  const timeoutMs = useBrutalSessionStore((s) => s.timeoutMs);
  const isFinished = useBrutalSessionStore((s) => s.isFinished());
  const answerStore = useBrutalSessionStore((s) => s.answer);
  const startStore = useBrutalSessionStore((s) => s.start);
  const resetStore = useBrutalSessionStore((s) => s.reset);

  const [bootState, setBootState] = useState<
    "idle" | "loading" | "ready" | "empty" | "error"
  >("idle");
  const [plan, setPlan] = useState<BrutalPlanResponse | null>(null);
  const [pendingPoolSmall, setPendingPoolSmall] = useState<{
    plan: BrutalPlanResponse;
    timeoutMs: BrutalTimeoutMs;
  } | null>(null);
  const [paused, setPaused] = useState(false);
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const questionStartRef = useRef(Date.now());

  const config = useMemo(() => parseConfig(searchParams), [searchParams]);

  // Bootstrap — fetch plan once per mount with the parsed config. Empty
  // cards with no warning → "nothing to drill" closure (0/0/0). Pool
  // small → stash plan and render confirm modal.
  useEffect(() => {
    if (bootState !== "idle") return;
    if (!config) {
      router.replace("/");
      return;
    }
    let cancelled = false;
    setBootState("loading");
    (async () => {
      try {
        const fetched = await getBrutalPlan(config.size);
        if (cancelled) return;
        const timeoutMsVal = (config.timeoutSec * 1000) as BrutalTimeoutMs;
        if (fetched.cards.length === 0) {
          setPlan(fetched);
          setBootState("empty");
          return;
        }
        if (fetched.warning === "pool_small") {
          setPendingPoolSmall({ plan: fetched, timeoutMs: timeoutMsVal });
          setBootState("ready");
          return;
        }
        startStore(fetched, timeoutMsVal);
        setPlan(fetched);
        setBootState("ready");
      } catch (err) {
        if (cancelled) return;
        setErrorMsg(
          (err as Error | null)?.message ?? "Could not load the drill.",
        );
        setBootState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [bootState, config, router, startStore]);

  // Tab-blur pause — single-line contract per the phase plan. We don't
  // pause during the `pendingPoolSmall` confirm because the timer isn't
  // running yet.
  useEffect(() => {
    const onVis = () => setPaused(document.hidden);
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  // Reset transient UI state whenever the queue head changes (new card
  // or retry of same card after requeue).
  const currentCard = queue[0] ?? null;
  const currentCardKey = currentCard
    ? `${currentCard.id}-${attempts[currentCard.id] ?? 0}`
    : null;

  useEffect(() => {
    setSelectedOption(null);
    setResult(null);
    setErrorMsg(null);
    questionStartRef.current = Date.now();
  }, [currentCardKey]);

  // Cleanup: reset the store on unmount so a back-nav doesn't leave
  // state lingering for the next Brutal session.
  useEffect(() => {
    return () => {
      resetStore();
    };
  }, [resetStore]);

  const confirmPoolSmall = useCallback(() => {
    if (!pendingPoolSmall) return;
    startStore(pendingPoolSmall.plan, pendingPoolSmall.timeoutMs);
    setPendingPoolSmall(null);
  }, [pendingPoolSmall, startStore]);

  const declinePoolSmall = useCallback(() => {
    setPendingPoolSmall(null);
    router.replace("/");
  }, [router]);

  const handleTimeout = useCallback(async () => {
    if (!currentCard || submitting || result) return;
    setSubmitting(true);
    try {
      await submitAnswer(
        currentCard.id,
        BRUTAL_TIMEOUT_SENTINEL,
        timeoutMs,
      );
    } catch {
      // Network failure on a timeout still has to advance the UI —
      // otherwise the user is stuck on a card they can't interact with.
      // We intentionally don't surface an inline error here; the next
      // card's submit will surface one if the backend is truly down.
    } finally {
      answerStore(currentCard.id, false);
      setSubmitting(false);
    }
  }, [answerStore, currentCard, result, submitting, timeoutMs]);

  const handleOptionClick = useCallback(
    async (optionKey: string) => {
      if (!currentCard || submitting || result) return;
      setSelectedOption(optionKey);
      setSubmitting(true);
      setErrorMsg(null);
      try {
        const elapsed = Date.now() - questionStartRef.current;
        const res = await submitAnswer(currentCard.id, optionKey, elapsed);
        setResult(res);
        answerStore(currentCard.id, res.is_correct);
      } catch (err) {
        setSelectedOption(null);
        setErrorMsg(
          (err as Error | null)?.message ??
            "Could not submit your answer. Try again.",
        );
      } finally {
        setSubmitting(false);
      }
    },
    [answerStore, currentCard, result, submitting],
  );

  const optionKeys = useMemo(
    () => (currentCard?.options ? Object.keys(currentCard.options).sort() : []),
    [currentCard],
  );

  // ── Render branches ──

  if (bootState === "loading" || bootState === "idle") {
    return (
      <div
        className="min-h-screen bg-background"
        data-testid="brutal-session-loading"
      />
    );
  }

  if (bootState === "error") {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center p-4">
        <div
          role="alert"
          data-testid="brutal-session-error"
          className="rounded-2xl bg-card p-6 card-shadow max-w-sm space-y-3 text-center"
        >
          <p className="text-sm text-destructive">{errorMsg}</p>
          <button
            type="button"
            onClick={() => router.replace("/")}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            Back to dashboard
          </button>
        </div>
      </div>
    );
  }

  if (bootState === "empty" || (isFinished && plan)) {
    const duration = startedAt > 0 ? Date.now() - startedAt : 0;
    return (
      <div className="min-h-screen bg-background py-12 px-4">
        <BrutalClosure
          durationMs={duration}
          maxStreak={maxStreak}
          masteredCount={mastered.size}
          forceRetiredCount={forceRetired.size}
          conceptFailTally={conceptFailTally}
          onBack={() => router.push("/")}
          onRunAnother={() => router.push("/?open_brutal=true")}
        />
      </div>
    );
  }

  if (pendingPoolSmall) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center p-4">
        <div
          role="dialog"
          aria-modal="true"
          data-testid="brutal-pool-small"
          className="rounded-2xl bg-card p-6 card-shadow max-w-sm space-y-4 text-center"
        >
          <p className="text-sm text-foreground">
            Only {pendingPoolSmall.plan.cards.length} cards available — drill
            anyway?
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={declinePoolSmall}
              data-testid="brutal-pool-small-no"
              className="flex-1 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40"
            >
              No
            </button>
            <button
              type="button"
              onClick={confirmPoolSmall}
              data-testid="brutal-pool-small-yes"
              className="flex-1 rounded-lg bg-amber-600 px-3 py-2 text-sm font-medium text-white hover:bg-amber-600/90"
            >
              Yes
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!currentCard) {
    // Transitional frame after every card cleared but before isFinished
    // snapshot picks up. Render nothing to avoid flashing an empty shell.
    return (
      <div
        className="min-h-screen bg-background"
        data-testid="brutal-session-transition"
      />
    );
  }

  return (
    <div className="min-h-screen bg-background py-8 px-4">
      <div className="mx-auto max-w-xl space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1 text-xs text-muted-foreground">
            <span
              className="flex items-center gap-1.5 text-amber-600"
              data-testid="brutal-session-streak"
            >
              <Flame className="size-3.5" />
              Streak {currentStreak} · max {maxStreak}
            </span>
            <span data-testid="brutal-session-progress">
              {mastered.size} / {mastered.size + queue.length} mastered
            </span>
          </div>
          <div
            className="shrink-0"
            // `key` forces remount on new card / retry — restarts the CSS
            // animation from 0 without touching JS clocks.
            key={currentCardKey ?? "no-card"}
          >
            <BrutalTimerRing
              timeoutMs={timeoutMs}
              paused={paused}
              onTimeout={() => void handleTimeout()}
            />
          </div>
        </div>

        <p
          className="text-base font-medium leading-relaxed"
          data-testid="brutal-session-question"
        >
          {currentCard.question}
        </p>

        <QuizOptions
          optionKeys={optionKeys}
          options={(currentCard.options ?? {}) as Record<string, string>}
          selectedOption={selectedOption}
          result={result}
          submitting={submitting}
          onOptionClick={(key) => void handleOptionClick(key)}
        />

        {errorMsg ? (
          <p role="alert" className="text-xs text-destructive">
            {errorMsg}
          </p>
        ) : null}

        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => router.push("/")}
            data-testid="brutal-session-exit"
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            Exit
          </button>
        </div>
      </div>
    </div>
  );
}
