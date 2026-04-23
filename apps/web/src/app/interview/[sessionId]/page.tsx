"use client";

/**
 * /interview/[sessionId] — active session UI (Phase 5 T6c).
 *
 * Responsibilities:
 *   1. Rehydrate state via `GET /interview/{id}` on mount (pause+resume).
 *   2. If session is finished → render <SummaryReport> + gap-save CTA.
 *   3. If in_progress:
 *       a. Current turn has no answer → show question + textarea.
 *       b. Current turn has answer+rubric (mid-session re-entry after
 *          browser crash) → show a Resume banner, then let the user
 *          proceed to the next question (which the backend already
 *          returned during the earlier SSE).
 *   4. Textarea Enter → stream answer → render rubric → swap to next Q.
 *   5. "End early" always visible → abandon → summary.
 *
 * The worst-3-turns heuristic for `SummaryReport.turnIds` is computed
 * by summing dim scores per turn and ascending-sorting — lower sum =
 * weaker answer. Ties break by later `turn_number` since later questions
 * are usually harder.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  Loader2,
  Send,
  ArrowLeft,
  LogOut,
  RefreshCcw,
  AlertCircle,
} from "lucide-react";
import {
  getInterviewSession,
  abandonInterview,
  streamInterviewAnswer,
  ApiError,
} from "@/lib/api";
import type {
  InterviewSessionState,
  TurnResponse,
  RubricScores,
  SummaryResponse,
  InterviewStreamEvent,
} from "@/lib/api/interview";
import { RubricPanel } from "@/components/interview/RubricPanel";
import { SummaryReport } from "@/components/interview/SummaryReport";

/** Sum rubric dim scores for a single turn (missing rubric = +Infinity). */
function turnScore(turn: TurnResponse): number {
  if (!turn.rubric) return Number.POSITIVE_INFINITY;
  return Object.values(turn.rubric.dimensions).reduce(
    (acc, d) => acc + (d.score ?? 0),
    0,
  );
}

/** Pick up to `n` weakest-scoring turn IDs; skip turns missing `id`. */
function pickWorstTurnIds(turns: TurnResponse[], n = 3): string[] {
  return turns
    .filter((t) => t.id && t.rubric)
    .slice()
    .sort((a, b) => {
      const diff = turnScore(a) - turnScore(b);
      if (diff !== 0) return diff;
      return b.turn_number - a.turn_number;
    })
    .slice(0, n)
    .map((t) => t.id as string);
}

type ViewPhase =
  | "loading"
  | "asking" // current Q waiting for textarea input
  | "submitting" // SSE in flight, rubric not yet received
  | "showing_rubric" // rubric received; waiting for next_q or completed
  | "completed"
  | "error";

function isFinished(status: string): boolean {
  return (
    status === "completed" ||
    status === "completed_early" ||
    status === "abandoned"
  );
}

export default function InterviewSessionPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.sessionId as string;

  const [state, setState] = useState<InterviewSessionState | null>(null);
  const [phase, setPhase] = useState<ViewPhase>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [currentQuestion, setCurrentQuestion] = useState<string>("");
  const [currentTurnNumber, setCurrentTurnNumber] = useState<number>(1);
  const [answerText, setAnswerText] = useState<string>("");
  const [liveRubric, setLiveRubric] = useState<RubricScores | null>(null);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [resumeNeeded, setResumeNeeded] = useState<boolean>(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Rehydrate on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await getInterviewSession(sessionId);
        if (cancelled) return;
        setState(s);
        if (isFinished(s.status)) {
          setSummary(s.summary ?? null);
          setPhase("completed");
          return;
        }
        // Find current (un-answered) turn or the last answered one.
        const lastTurn = s.turns[s.turns.length - 1];
        if (!lastTurn) {
          setLoadError("Session has no turns yet — try starting again.");
          setPhase("error");
          return;
        }
        if (lastTurn.answer == null) {
          setCurrentQuestion(lastTurn.question);
          setCurrentTurnNumber(lastTurn.turn_number);
          setPhase("asking");
        } else {
          // Mid-session re-entry: the turn was graded but we lost the
          // next_question payload (tab crash during SSE). Show a resume
          // banner that asks the server for a fresh rehydrate — the
          // backend stores the next turn lazily only after the user
          // submits, so here we just invite the user to submit again.
          setCurrentQuestion(lastTurn.question);
          setCurrentTurnNumber(lastTurn.turn_number);
          setLiveRubric(lastTurn.rubric ?? null);
          setResumeNeeded(true);
          setPhase("showing_rubric");
        }
      } catch (err) {
        if (cancelled) return;
        setLoadError(
          err instanceof Error ? err.message : "Failed to load session.",
        );
        setPhase("error");
      }
    })();
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, [sessionId]);

  const submitAnswer = useCallback(async () => {
    const text = answerText.trim();
    if (!text) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setPhase("submitting");
    setLiveRubric(null);
    setResumeNeeded(false);

    try {
      for await (const evt of streamInterviewAnswer(
        sessionId,
        text,
        ctrl.signal,
      ) as AsyncGenerator<InterviewStreamEvent>) {
        if (evt.event === "rubric") {
          setLiveRubric({
            dimensions: evt.data.dimensions,
            feedback_short: evt.data.feedback_short,
          });
          setPhase("showing_rubric");
          // Update in-memory session turns so worst-3 picker has fresh data.
          setState((prev) =>
            prev
              ? {
                  ...prev,
                  completed_turns: evt.data.turn_number,
                  turns: prev.turns.map((t) =>
                    t.turn_number === evt.data.turn_number
                      ? {
                          ...t,
                          answer: text,
                          rubric: {
                            dimensions: evt.data.dimensions,
                            feedback_short: evt.data.feedback_short,
                          },
                        }
                      : t,
                  ),
                }
              : prev,
          );
        } else if (evt.event === "next_question") {
          setCurrentQuestion(evt.data.question);
          setCurrentTurnNumber(evt.data.turn_number);
          setAnswerText("");
          setLiveRubric(null);
          setPhase("asking");
          // Optimistically append a placeholder turn so the worst-3
          // picker sees the right ordering on the next rubric.
          setState((prev) =>
            prev
              ? {
                  ...prev,
                  turns: [
                    ...prev.turns,
                    {
                      turn_number: evt.data.turn_number,
                      question: evt.data.question,
                      question_type: evt.data.question_type,
                      grounding_source: evt.data.grounding_source ?? null,
                      answer: null,
                      rubric: null,
                    },
                  ],
                }
              : prev,
          );
        } else if (evt.event === "completed") {
          setSummary(evt.data.summary);
          setPhase("completed");
          setState((prev) =>
            prev ? { ...prev, status: "completed", summary: evt.data.summary } : prev,
          );
        } else if (evt.event === "error") {
          setLoadError(evt.data.error);
          setPhase("error");
        }
      }
    } catch (err) {
      if (ctrl.signal.aborted) return;
      setLoadError(
        err instanceof ApiError
          ? err.detail ?? err.message
          : err instanceof Error
          ? err.message
          : "Stream failed.",
      );
      setPhase("error");
    }
  }, [answerText, sessionId]);

  const handleAbandon = useCallback(async () => {
    try {
      const res = await abandonInterview(sessionId);
      setState(res);
      setSummary(res.summary ?? null);
      setPhase("completed");
    } catch (err) {
      setLoadError(
        err instanceof Error ? err.message : "Failed to end session.",
      );
      setPhase("error");
    }
  }, [sessionId]);

  const onTextareaKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      // Enter submits; Shift+Enter inserts a newline (standard chat UX).
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void submitAnswer();
      }
    },
    [submitAnswer],
  );

  const worstTurnIds = useMemo(
    () => (state ? pickWorstTurnIds(state.turns, 3) : []),
    [state],
  );

  // ---------- rendering branches ----------

  if (phase === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6">
        <div
          data-testid="interview-session-error"
          className="flex max-w-md flex-col items-start gap-3 rounded-lg border border-red-300/60 bg-red-50/80 p-5 text-red-950"
        >
          <div className="flex items-start gap-2">
            <AlertCircle className="mt-0.5 size-4 text-red-600" />
            <span className="text-sm font-semibold">
              {loadError ?? "Something went wrong."}
            </span>
          </div>
          <Link
            href="/interview"
            className="inline-flex items-center gap-1 text-xs text-red-700 underline"
          >
            <ArrowLeft className="size-3" /> back to interview start
          </Link>
        </div>
      </div>
    );
  }

  if (phase === "completed") {
    return (
      <div className="min-h-screen bg-background p-6">
        <div className="mx-auto flex w-full max-w-xl flex-col gap-4">
          {summary ? (
            <SummaryReport
              summary={summary}
              sessionId={sessionId}
              turnIds={worstTurnIds}
              onSaved={() => router.refresh()}
            />
          ) : (
            <div
              data-testid="interview-no-summary"
              className="rounded-lg border border-border bg-card p-4 text-sm text-foreground"
            >
              Session ended without a summary (likely abandoned before any
              turn was graded).
              <Link href="/interview" className="ml-1 underline">
                Start a new one
              </Link>
              .
            </div>
          )}
        </div>
      </div>
    );
  }

  const total = state?.total_turns ?? 0;
  const completed = state?.completed_turns ?? 0;

  return (
    <div className="min-h-screen bg-background p-6">
      <div className="mx-auto flex w-full max-w-xl flex-col gap-5">
        {/* Progress + end-early */}
        <header className="flex items-center justify-between">
          <div className="flex flex-col gap-0.5">
            <p
              className="text-xs uppercase tracking-wide text-muted-foreground"
              data-testid="interview-progress"
            >
              Turn {currentTurnNumber} of {total}
              {total > 0 && (
                <span className="ml-2 text-muted-foreground">
                  ({completed} graded)
                </span>
              )}
            </p>
            <h1 className="text-lg font-semibold text-foreground">
              {state?.project_focus} · {state?.mode}
            </h1>
          </div>
          <button
            type="button"
            data-testid="interview-end-early"
            onClick={handleAbandon}
            className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-3 py-1.5 text-xs text-foreground hover:border-red-300 hover:text-red-700"
          >
            <LogOut className="size-3" />
            End early
          </button>
        </header>

        {/* Resume banner (pause+resume re-entry) */}
        {resumeNeeded && (
          <div
            data-testid="interview-resume-banner"
            className="flex items-start gap-2 rounded-md border border-blue-200/60 bg-blue-50/70 px-3 py-2 text-sm text-blue-950"
          >
            <RefreshCcw className="mt-0.5 size-4 text-blue-600" />
            <span>
              Resumed from turn {currentTurnNumber} of {total}. Scroll to
              rubric below — new question will load when you submit.
            </span>
          </div>
        )}

        {/* Current question */}
        <section
          data-testid="interview-question"
          className="rounded-lg border border-border bg-card p-4"
        >
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Question
          </p>
          <p className="mt-1 text-sm text-foreground whitespace-pre-wrap">
            {currentQuestion}
          </p>
        </section>

        {/* Textarea */}
        {phase !== "showing_rubric" || !liveRubric ? (
          <section className="flex flex-col gap-2">
            <label
              htmlFor="interview-answer"
              className="text-xs uppercase tracking-wide text-muted-foreground"
            >
              Your answer (Enter submits · Shift+Enter newline)
            </label>
            <textarea
              id="interview-answer"
              ref={textareaRef}
              data-testid="interview-answer-textarea"
              value={answerText}
              onChange={(e) => setAnswerText(e.target.value)}
              onKeyDown={onTextareaKeyDown}
              disabled={phase === "submitting"}
              rows={6}
              className="w-full rounded-lg border border-border bg-card p-3 text-sm text-foreground focus:border-brand focus:outline-none disabled:opacity-60"
              placeholder="Walk me through it..."
            />
            <button
              type="button"
              data-testid="interview-submit-answer"
              onClick={() => void submitAnswer()}
              disabled={phase === "submitting" || !answerText.trim()}
              className="inline-flex h-10 w-fit items-center justify-center gap-2 rounded-lg bg-brand px-4 text-sm font-semibold text-brand-foreground hover:opacity-90 disabled:opacity-50"
            >
              {phase === "submitting" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Send className="size-4" />
              )}
              {phase === "submitting" ? "Grading..." : "Submit answer"}
            </button>
          </section>
        ) : null}

        {/* Rubric panel */}
        {liveRubric && (
          <RubricPanel rubric={liveRubric} turnNumber={currentTurnNumber} />
        )}
      </div>
    </div>
  );
}
