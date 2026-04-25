"use client";

/**
 * `<GenerateRoomModal>` — Phase 16b Bundle B (v2 polish).
 *
 * Modal that submits a room-generation request against
 * `POST /api/paths/generate-room` and (when the API returns a `job_id`)
 * subscribes to the SSE stream via `useRoomGenerationStream` to surface
 * progress. On `completed` it routes the user to the resulting mission;
 * on `error` it shows calm copy mapped from the error code with an
 * optional Retry control.
 *
 * v2 polish (this revision)
 * -------------------------
 * - 4-step progress visual with per-row state (done / current / pending),
 *   replacing the flat 4-bar segmented strip. Test ids
 *   `generation-progress-step-0..3` are the contract.
 * - Error block uses amber border (`--warning`) per ADHD §11 rule 11.
 *   Retryable codes (topic_guard, generic) get a Retry button that
 *   restores the form preserving the user's prior inputs. Non-retryable
 *   codes (path_course_mismatch, daily_generation_cap_exceeded,
 *   not_found) only show Close.
 * - Success state on `completed` shows "Room ready" + a 2s auto-redirect
 *   countdown alongside `View room` (immediate) and `Stay here` (cancel
 *   redirect) buttons.
 *
 * Concurrency contract
 * --------------------
 * - The lib `@/lib/api/path-generation` is owned by Subagent B. We never
 *   write to any state owned by Subagent B. Only the modal's local
 *   `phase` / `streamJobId` / `errorCode` transitions are owned here.
 *
 * ADHD rules honoured (ТЗ §11)
 * ----------------------------
 * - Esc dismisses (rule 5) — except during `persisting`, where a DB write
 *   is mid-flight; closing then would orphan a row, so we intercept.
 * - Calm copy (§10): "miss" / "couldn't generate", never "wrong/failed".
 * - One CTA per region (rule 9). The submit button is the only primary
 *   on the form; success offers two equal-weight buttons for parity.
 * - Errors are amber, never red (rule 11). No shake animation, no toast,
 *   no sound, no confetti (rules 11+12).
 *
 * Design tokens (ТЗ §8)
 * ---------------------
 * - Motion: `--dur-normal` (200ms) for status transitions; `--dur-fast`
 *   (120ms) for hover.
 * - Color: `--accent-primary` for the current progress step; `--success`
 *   for completed steps; `--warning` for errors; `text-muted-foreground`
 *   for pending. No new tokens.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  generateRoom,
  type GenerateRoomRequest,
  type GenerateRoomDifficulty,
} from "@/lib/api/path-generation";
import { useRoomGenerationStream } from "@/hooks/use-room-generation-stream";

type RoomDifficulty = GenerateRoomDifficulty;

interface GenerateRoomModalProps {
  pathId: string;
  courseId: string;
  pathSlug: string;
  isOpen: boolean;
  onClose: () => void;
}

type Phase = "idle" | "submitting" | "streaming" | "reused" | "done" | "error";

/**
 * Codes for which "Try again" is meaningful — i.e. the same form might
 * succeed after the user edits. Non-retryable codes are terminal for
 * this session (daily cap) or imply structural mismatch the user can't
 * fix in-modal (path/course) — those only show Close.
 *
 * Generic / unknown is treated as retryable: most "unknown" failures are
 * transient model hiccups where retry just works.
 */
const RETRYABLE_ERROR_CODES = new Set<string>([
  "topic_guard",
  "unknown",
]);

function isRetryableError(code: string | null): boolean {
  // No code at all → generic transient → retryable.
  if (code === null) return true;
  return RETRYABLE_ERROR_CODES.has(code);
}

/** Auto-redirect window on success. Long enough for the user to see
 *  what happened, short enough to feel snappy. ТЗ §10. */
const SUCCESS_REDIRECT_MS = 2000;
/** Reused-room navigation delay (kept short; nothing to celebrate). */
const REUSED_REDIRECT_MS = 600;

const DIFFICULTY_OPTIONS: ReadonlyArray<{
  value: RoomDifficulty;
  label: string;
}> = [
  { value: "beginner", label: "Beginner" },
  { value: "intermediate", label: "Intermediate" },
  { value: "advanced", label: "Advanced" },
];

const TASK_COUNT_OPTIONS: ReadonlyArray<number> = [3, 4, 5, 6, 7, 8];

const TOPIC_MIN = 3;
const TOPIC_MAX = 120;

/** Status chip copy — kept calm + matter-of-fact per §10. Streaming
 *  statuses map to one short label; we never expose raw API enums. */
const STATUS_LABEL: Record<string, string> = {
  queued: "Queued",
  outline: "Drafting outline",
  tasks: "Writing tasks",
  persisting: "Saving room",
  completed: "Done",
  error: "Couldn't generate",
};

/**
 * The four rows in the progress visual. Order is fixed (no skipping).
 * Each entry pairs a stable testid suffix and a human-readable label.
 * Index ↔ stream status mapping happens in {@link stepStateForStatus}.
 */
const PROGRESS_ROWS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "outline", label: "Drafting outline" },
  { key: "tasks", label: "Writing tasks" },
  { key: "persisting", label: "Saving room" },
  { key: "completed", label: "Done" },
];

/** Error-code → friendly copy. Generic fallback intentionally suggests
 *  rephrasing rather than blaming the user. */
const ERROR_COPY: Record<string, string> = {
  topic_guard: "That topic was rejected. Rephrase and try again.",
  path_course_mismatch:
    "This path and course don't match. Pick a different course.",
  daily_generation_cap_exceeded: "Daily limit reached. Try tomorrow.",
};

const GENERIC_ERROR_COPY =
  "Couldn't generate this one. Try a slightly different topic.";

type StepState = "done" | "current" | "pending";

/**
 * Map a stream `status` to the per-row state for each of the four
 * progress rows. Rules:
 *
 *   - `queued`     → all pending, row 0 marked current (to give a
 *                    pulsing indicator while the worker spins up).
 *   - `outline`    → row 0 current, rest pending.
 *   - `tasks`      → row 0 done, row 1 current, rest pending.
 *   - `persisting` → rows 0–1 done, row 2 current, row 3 pending.
 *   - `completed`  → all four rows done.
 *   - anything else → all pending (defensive — shouldn't happen).
 */
function stepStateForStatus(status: string, rowIndex: number): StepState {
  // Pivot index = the row that's currently active (or -1 if none).
  let activeIdx: number;
  let allDone = false;
  switch (status) {
    case "queued":
    case "outline":
      activeIdx = 0;
      break;
    case "tasks":
      activeIdx = 1;
      break;
    case "persisting":
      activeIdx = 2;
      break;
    case "completed":
      activeIdx = 3;
      allDone = true;
      break;
    default:
      activeIdx = -1;
  }
  if (allDone) return "done";
  if (rowIndex < activeIdx) return "done";
  if (rowIndex === activeIdx) return "current";
  return "pending";
}

export function GenerateRoomModal({
  pathId,
  courseId,
  pathSlug,
  isOpen,
  onClose,
}: GenerateRoomModalProps) {
  const router = useRouter();

  // Form state. We deliberately preserve these values across the
  // submit→error→retry cycle so the user doesn't have to retype.
  const [topic, setTopic] = useState("");
  const [difficulty, setDifficulty] = useState<RoomDifficulty>("beginner");
  const [taskCount, setTaskCount] = useState<number>(5);

  // Phase + side-effect state
  const [phase, setPhase] = useState<Phase>("idle");
  const [streamJobId, setStreamJobId] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [reusedRoomId, setReusedRoomId] = useState<string | null>(null);
  // The room id we'll navigate to once the success countdown elapses.
  // Captured at `completed` so a manual "View room" click doesn't have
  // to re-derive it from the stream.
  const [successRoomId, setSuccessRoomId] = useState<string | null>(null);

  // Track whether navigation has been scheduled so we don't double-fire.
  const navigateTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset form/phase whenever the modal opens. We deliberately keep
  // values empty on close so a re-open never shows stale state.
  useEffect(() => {
    if (!isOpen) return;
    setTopic("");
    setDifficulty("beginner");
    setTaskCount(5);
    setPhase("idle");
    setStreamJobId(null);
    setErrorCode(null);
    setReusedRoomId(null);
    setSuccessRoomId(null);
  }, [isOpen]);

  // Cleanup any pending navigation timer on unmount / phase reset to
  // avoid a stale push() after the modal has already closed.
  useEffect(() => {
    return () => {
      if (navigateTimerRef.current !== null) {
        clearTimeout(navigateTimerRef.current);
        navigateTimerRef.current = null;
      }
    };
  }, []);

  const stream = useRoomGenerationStream(streamJobId);

  // React to stream completion / error. We split this from submit so
  // the SSE hook drives transitions exclusively while streaming.
  useEffect(() => {
    if (phase !== "streaming" || !stream) return;
    if (stream.status === "completed" && stream.roomId) {
      const roomId = stream.roomId;
      setSuccessRoomId(roomId);
      setPhase("done");
      // 2s default — gives the user a beat to register success and the
      // option to bail via "Stay here". `clearTimeout` lives on the
      // Stay-here handler.
      navigateTimerRef.current = setTimeout(() => {
        router.push(`/tracks/${pathSlug}/missions/${roomId}`);
      }, SUCCESS_REDIRECT_MS);
    } else if (stream.status === "error") {
      setErrorCode(stream.error?.code ?? null);
      setPhase("error");
    }
  }, [phase, stream, router, pathSlug]);

  const trimmedTopic = topic.trim();
  const topicValid =
    trimmedTopic.length >= TOPIC_MIN && trimmedTopic.length <= TOPIC_MAX;
  const submitDisabled = !topicValid || phase !== "idle";

  const handleSubmit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      if (submitDisabled) return;

      setPhase("submitting");
      setErrorCode(null);

      const req: GenerateRoomRequest = {
        path_id: pathId,
        course_id: courseId,
        topic: trimmedTopic,
        difficulty,
        task_count: taskCount,
      };

      try {
        const res = await generateRoom(req);
        // Discriminated union narrowing: `reused: true` → has `room_id`;
        // `reused: false` → has `job_id`. We branch on the flag and let
        // TS narrow each arm.
        if (res.reused) {
          setReusedRoomId(res.room_id);
          setPhase("reused");
          const roomId = res.room_id;
          navigateTimerRef.current = setTimeout(() => {
            router.push(`/tracks/${pathSlug}/missions/${roomId}`);
          }, REUSED_REDIRECT_MS);
          return;
        }
        if (res.job_id) {
          setStreamJobId(res.job_id);
          setPhase("streaming");
          return;
        }
        // Defensive: API returned neither reuse nor job_id. Fall through
        // to a generic error rather than spinning forever.
        setPhase("error");
      } catch (err: unknown) {
        // Try to surface a structured error_code if the API client put
        // one on the thrown error. Otherwise generic.
        const code = extractErrorCode(err);
        setErrorCode(code);
        setPhase("error");
      }
    },
    [
      submitDisabled,
      pathId,
      courseId,
      trimmedTopic,
      difficulty,
      taskCount,
      router,
      pathSlug,
    ],
  );

  /** Cancel the pending success-redirect timer (if any). Used by Stay
   *  here, View room, and any handler that takes manual control of
   *  navigation away from the auto-redirect. */
  const cancelNavigateTimer = useCallback(() => {
    if (navigateTimerRef.current !== null) {
      clearTimeout(navigateTimerRef.current);
      navigateTimerRef.current = null;
    }
  }, []);

  /** "Try again" — return to the form preserving the user's inputs.
   *  We tear down any active stream subscription explicitly so a stale
   *  job_id can't push a late event into the now-form view. */
  const handleRetry = useCallback(() => {
    cancelNavigateTimer();
    if (typeof stream?.disconnect === "function") {
      stream.disconnect();
    }
    setStreamJobId(null);
    setErrorCode(null);
    setReusedRoomId(null);
    setSuccessRoomId(null);
    setPhase("idle");
  }, [cancelNavigateTimer, stream]);

  /** "View room" — navigate immediately, skipping the auto-redirect. */
  const handleViewRoom = useCallback(() => {
    if (!successRoomId) return;
    cancelNavigateTimer();
    router.push(`/tracks/${pathSlug}/missions/${successRoomId}`);
  }, [cancelNavigateTimer, router, pathSlug, successRoomId]);

  /** "Stay here" — cancel the auto-redirect; the user can dismiss the
   *  modal manually. They keep the success block on screen. */
  const handleStayHere = useCallback(() => {
    cancelNavigateTimer();
  }, [cancelNavigateTimer]);

  const isPersisting = stream?.status === "persisting";

  const handleOpenChange = (next: boolean) => {
    if (next) return;
    // Block close while DB writes are in-flight to avoid orphan rows.
    if (isPersisting) return;
    onClose();
  };

  // Esc handling — Radix Dialog already wires Esc to onOpenChange(false),
  // but we additionally short-circuit if persisting. The intercept lives
  // in `handleOpenChange` above; we also bind a capture-phase listener so
  // tests that fire `keydown(Escape)` directly observe the same behavior.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (isPersisting) {
        e.stopPropagation();
        e.preventDefault();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [isOpen, isPersisting]);

  const showCloseControls = phase !== "submitting" && !isPersisting;

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogContent
        data-testid="generate-room-modal"
        showCloseButton={showCloseControls}
        onEscapeKeyDown={(e) => {
          if (isPersisting) e.preventDefault();
        }}
        onPointerDownOutside={(e) => {
          if (isPersisting) e.preventDefault();
        }}
        onInteractOutside={(e) => {
          if (isPersisting) e.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle data-testid="generate-room-modal-title">
            Generate room
          </DialogTitle>
          <DialogDescription>
            One topic. We draft an outline, then tasks.
          </DialogDescription>
        </DialogHeader>

        {(phase === "idle" || phase === "submitting") && (
          <form
            onSubmit={handleSubmit}
            data-testid="generate-room-form"
            className="flex flex-col gap-4"
          >
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium text-foreground">Topic</span>
              <Input
                type="text"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="e.g. Python decorators"
                data-testid="generate-room-topic"
                minLength={TOPIC_MIN}
                maxLength={TOPIC_MAX}
                disabled={phase === "submitting"}
                autoFocus
              />
              <span className="text-xs text-muted-foreground">
                {TOPIC_MIN}–{TOPIC_MAX} characters
              </span>
            </label>

            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium text-foreground">Difficulty</span>
              <select
                value={difficulty}
                onChange={(e) =>
                  setDifficulty(e.target.value as RoomDifficulty)
                }
                data-testid="generate-room-difficulty"
                disabled={phase === "submitting"}
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:opacity-50"
              >
                {DIFFICULTY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium text-foreground">Tasks</span>
              <select
                value={taskCount}
                onChange={(e) => setTaskCount(Number(e.target.value))}
                data-testid="generate-room-task-count"
                disabled={phase === "submitting"}
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:opacity-50"
              >
                {TASK_COUNT_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>

            <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:justify-end">
              <Button
                type="button"
                variant="outline"
                onClick={onClose}
                data-testid="generate-room-cancel"
                disabled={phase === "submitting"}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                data-testid="generate-room-submit"
                disabled={submitDisabled}
                aria-busy={phase === "submitting"}
              >
                {phase === "submitting" ? "Submitting" : "Generate room"}
              </Button>
            </div>
          </form>
        )}

        {phase === "reused" && (
          <div data-testid="generate-room-reused" className="text-sm">
            <p className="text-foreground">Room already exists. Opening it.</p>
            {reusedRoomId ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Heading to your existing room.
              </p>
            ) : null}
          </div>
        )}

        {phase === "streaming" && (
          <StreamingPanel status={stream?.status ?? "queued"} />
        )}

        {phase === "done" && (
          <SuccessPanel
            onViewRoom={handleViewRoom}
            onStayHere={handleStayHere}
            disableViewRoom={!successRoomId}
          />
        )}

        {phase === "error" && (
          <ErrorPanel
            errorCode={errorCode}
            onRetry={handleRetry}
            onClose={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

/** The streaming progress panel — a calm status chip plus the 4-row
 *  step list. Each row carries its own state (done / current / pending)
 *  so the user always sees where in the pipeline we are. */
function StreamingPanel({ status }: { status: string }) {
  const label = STATUS_LABEL[status] ?? "Working";
  // For aria-valuenow we count completed rows + the current row.
  const completedCount = PROGRESS_ROWS.reduce((n, _, i) => {
    const s = stepStateForStatus(status, i);
    return s === "done" ? n + 1 : s === "current" ? n + 1 : n;
  }, 0);

  return (
    <div data-testid="generate-room-streaming" className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span
          data-testid="generate-room-status-chip"
          className="inline-flex items-center rounded-full border border-border bg-muted/40 px-3 py-1 text-xs font-medium text-foreground transition-colors"
          style={{ transitionDuration: "var(--dur-normal)" }}
        >
          {label}
        </span>
      </div>
      <ol
        data-testid="generate-room-progress"
        className="flex flex-col gap-2"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={PROGRESS_ROWS.length}
        aria-valuenow={completedCount}
      >
        {PROGRESS_ROWS.map((row, i) => {
          const state = stepStateForStatus(status, i);
          return (
            <li
              key={row.key}
              data-testid={`generation-progress-step-${i}`}
              data-step-state={state}
              className="flex items-center gap-3 text-sm transition-colors"
              style={{ transitionDuration: "var(--dur-normal)" }}
            >
              <StepIndicator state={state} />
              <span
                className={
                  state === "current"
                    ? "font-medium text-foreground"
                    : state === "done"
                      ? "text-muted-foreground"
                      : "text-muted-foreground"
                }
              >
                {row.label}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Visual marker for a single progress row. Done rows show a check on
 *  a success-tinted disc; current shows a pulsing emerald dot; pending
 *  shows a hollow muted circle. No shake / no sound (ADHD §11). */
function StepIndicator({ state }: { state: StepState }) {
  if (state === "done") {
    return (
      <span
        aria-hidden="true"
        className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-success/20 text-success"
      >
        <svg
          viewBox="0 0 16 16"
          className="h-3 w-3"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="3.5,8.5 6.5,11.5 12.5,4.5" />
        </svg>
      </span>
    );
  }
  if (state === "current") {
    return (
      <span
        aria-hidden="true"
        className="relative inline-flex h-5 w-5 items-center justify-center"
      >
        {/* Soft pulsing halo using Tailwind's animate-ping — calm
         *  per ADHD §11 (no shake), color = --accent-primary. */}
        <span className="absolute inline-flex h-5 w-5 animate-ping rounded-full bg-brand/40" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand" />
      </span>
    );
  }
  return (
    <span
      aria-hidden="true"
      className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-muted-foreground/40"
    />
  );
}

/** Success block (Phase 16b v2). Auto-redirect runs in parent; we just
 *  surface the affordances. The "Stay here" button cancels the timer
 *  via the parent's `onStayHere` callback so the user can linger. */
function SuccessPanel({
  onViewRoom,
  onStayHere,
  disableViewRoom,
}: {
  onViewRoom: () => void;
  onStayHere: () => void;
  disableViewRoom: boolean;
}) {
  return (
    <div
      data-testid="generation-success-block"
      // Keep the existing testid for backward compat with prior tests.
      className="flex flex-col gap-3 text-sm"
    >
      <div data-testid="generate-room-done">
        <p className="text-foreground font-medium">Room ready</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Opening it in 2 seconds…
        </p>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
        <Button
          type="button"
          variant="outline"
          onClick={onStayHere}
          data-testid="generation-success-stay"
        >
          Stay here
        </Button>
        <Button
          type="button"
          onClick={onViewRoom}
          disabled={disableViewRoom}
          data-testid="generation-success-view"
        >
          View room
        </Button>
      </div>
    </div>
  );
}

/** Error block — amber-bordered (ТЗ ADHD §11 rule 11), with a Retry
 *  button only for codes the user can recover from in-place. */
function ErrorPanel({
  errorCode,
  onRetry,
  onClose,
}: {
  errorCode: string | null;
  onRetry: () => void;
  onClose: () => void;
}) {
  const retryable = isRetryableError(errorCode);
  return (
    <div
      data-testid="generation-error-block"
      // Keep the existing testid for backward compat with prior tests.
      role="alert"
      className="flex flex-col gap-3 rounded-md border border-warning/60 bg-warning/10 p-3 text-sm"
    >
      <p data-testid="generate-room-error" className="text-foreground">
        {errorCopy(errorCode)}
      </p>
      <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
        <Button
          type="button"
          variant="outline"
          onClick={onClose}
          data-testid="generate-room-error-close"
        >
          Close
        </Button>
        {retryable && (
          <Button
            type="button"
            onClick={onRetry}
            data-testid="generation-error-retry"
          >
            Try again
          </Button>
        )}
      </div>
    </div>
  );
}

function errorCopy(code: string | null): string {
  if (code && ERROR_COPY[code]) return ERROR_COPY[code];
  return GENERIC_ERROR_COPY;
}

/** Extracts an error_code from a thrown value if the API client surfaced
 *  one. We support a couple of shapes defensively because Subagent B's
 *  client is concurrent work — its exact error contract may shift. */
function extractErrorCode(err: unknown): string | null {
  if (!err || typeof err !== "object") return null;
  const e = err as Record<string, unknown>;
  // Direct `code` field.
  if (typeof e.code === "string") return e.code;
  // `errorCode` camelCase variant.
  if (typeof e.errorCode === "string") return e.errorCode;
  // Nested `detail.error` matching the FastAPI 400 shape.
  const detail = e.detail;
  if (detail && typeof detail === "object") {
    const d = detail as Record<string, unknown>;
    if (typeof d.error === "string") return d.error;
  }
  // 429 fallback.
  if (typeof e.message === "string" && e.message.includes("daily_generation_cap_exceeded")) {
    return "daily_generation_cap_exceeded";
  }
  return null;
}
