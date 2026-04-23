"use client";

/**
 * Summary report — end-of-session inline-math recap + "Save N gap
 * flashcards" CTA (Phase 5 T6e).
 *
 * Data comes from the backend's deterministic summary (no LLM): average
 * per dimension, 2 weakest dims, optional `worst_turn_id`. When the user
 * presses Save Gaps we POST the pre-selected turn IDs — by default that's
 * the 3 lowest-scoring turns, which the parent derives from the full
 * transcript and passes in via `turnIds`.
 *
 * This component is intentionally dumb: the gap-picking heuristic lives
 * in the parent page (where the turn list is). All we do here is send
 * the batch and surface success via `onSaved`.
 */

import { useCallback, useState } from "react";
import Link from "next/link";
import { CheckCircle2, AlertCircle, Loader2 } from "lucide-react";
import { saveInterviewGaps, ApiError } from "@/lib/api";
import type { SummaryResponse } from "@/lib/api/interview";

interface Props {
  summary: SummaryResponse;
  sessionId: string;
  /** Pre-selected turn IDs to spawn flashcards from (parent picks the N worst). */
  turnIds: string[];
  onSaved?: (result: { saved_count: number }) => void;
}

type Phase = "idle" | "saving" | "saved" | "error";

function formatAvg(value: number): string {
  return value.toFixed(1);
}

export function SummaryReport({ summary, sessionId, turnIds, onSaved }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [savedCount, setSavedCount] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const weakestSet = new Set(summary.weakest_dimensions);
  const dimEntries = Object.entries(summary.avg_by_dimension);

  const saveGaps = useCallback(async () => {
    if (!turnIds.length) return;
    setPhase("saving");
    setErrorMsg(null);
    try {
      const res = await saveInterviewGaps(sessionId, turnIds);
      setSavedCount(res.saved_count);
      setPhase("saved");
      onSaved?.({ saved_count: res.saved_count });
    } catch (err) {
      setErrorMsg(
        err instanceof ApiError
          ? err.detail ?? err.message
          : err instanceof Error
          ? err.message
          : "Save failed. Try again.",
      );
      setPhase("error");
    }
  }, [sessionId, turnIds, onSaved]);

  return (
    <div
      data-testid="summary-report"
      className="flex flex-col gap-4 rounded-lg border border-border bg-card p-5"
    >
      <header className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold text-foreground">
          Session summary
        </h2>
        <p className="text-xs text-muted-foreground">
          Weakest dims are highlighted — drill them tomorrow.
        </p>
      </header>

      {/* Averages table */}
      <div
        data-testid="summary-averages"
        className="flex flex-col gap-2 rounded-md bg-muted/50 px-3 py-2"
      >
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Average per dimension
        </p>
        <ul className="flex flex-col gap-1">
          {dimEntries.map(([dim, avg]) => {
            const isWeak = weakestSet.has(dim);
            return (
              <li
                key={dim}
                data-testid={`summary-avg-${dim}`}
                data-is-weak={isWeak ? "1" : "0"}
                className={`flex items-center justify-between text-sm ${
                  isWeak ? "font-semibold text-red-700" : "text-foreground"
                }`}
              >
                <span>
                  {dim}
                  {isWeak && (
                    <span
                      className="ml-2 rounded bg-red-100 px-1.5 py-0.5 text-[10px] uppercase text-red-700"
                      data-testid={`summary-weak-tag-${dim}`}
                    >
                      weakest
                    </span>
                  )}
                </span>
                <span>{formatAvg(avg)} / 5</span>
              </li>
            );
          })}
        </ul>
      </div>

      {summary.total_answer_time_s != null && (
        <p
          data-testid="summary-time"
          className="text-xs text-muted-foreground"
        >
          Total answering time: {Math.round(summary.total_answer_time_s)}s
          {summary.answer_time_ms_avg != null
            ? ` (avg ${Math.round(summary.answer_time_ms_avg / 1000)}s per turn)`
            : ""}
        </p>
      )}

      {/* Save gaps CTA */}
      <div className="flex flex-col gap-2">
        {phase !== "saved" && (
          <button
            type="button"
            data-testid="summary-save-gaps"
            onClick={saveGaps}
            disabled={phase === "saving" || !turnIds.length}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-brand px-4 text-sm font-semibold text-brand-foreground hover:opacity-90 disabled:opacity-50"
          >
            {phase === "saving" && <Loader2 className="size-4 animate-spin" />}
            {phase === "saving"
              ? "Saving..."
              : `Save ${turnIds.length} gap flashcard${turnIds.length === 1 ? "" : "s"}`}
          </button>
        )}

        {phase === "saved" && (
          <div
            data-testid="summary-saved"
            role="status"
            className="flex items-center gap-2 rounded-md border border-emerald-300/60 bg-emerald-50/80 px-3 py-2 text-sm text-emerald-950"
          >
            <CheckCircle2 className="size-4 text-emerald-600" />
            <span>
              Saved {savedCount} card{savedCount === 1 ? "" : "s"} — drill
              them tomorrow from{" "}
              <Link href="/session/daily" className="underline">
                daily
              </Link>
              .
            </span>
          </div>
        )}

        {phase === "error" && errorMsg && (
          <div
            data-testid="summary-save-error"
            role="alert"
            className="flex items-start gap-2 rounded-md border border-red-300/60 bg-red-50/80 px-3 py-2 text-sm text-red-950"
          >
            <AlertCircle className="mt-0.5 size-4 text-red-600" />
            <span>{errorMsg}</span>
          </div>
        )}
      </div>

      {/* Back CTA */}
      <Link
        href="/"
        data-testid="summary-back"
        className="self-start text-xs text-muted-foreground underline hover:text-foreground"
      >
        Back to dashboard
      </Link>
    </div>
  );
}

export default SummaryReport;
