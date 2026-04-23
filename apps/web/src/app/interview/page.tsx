"use client";

/**
 * /interview — start form (Phase 5 T6b).
 *
 * User picks `project_focus` + `mode` + `duration`, submits, lands on
 * `/interview/[sessionId]`. Quick 3Q is the primary CTA (flag #3, A) to
 * keep the first session ADHD-safe (~8 min).
 *
 * If backend rejects with 400 `content_empty` (behavioral/mixed without
 * ≥2 filled stories), we render a banner that links the user to
 * `/content/star_stories.md` — the instruction to fill more stories
 * lives in the plan, not in the app, so we surface the raw CTA URL
 * as the backend returns it.
 */

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Loader2, ArrowRight, AlertCircle } from "lucide-react";
import { startInterview, ApiError } from "@/lib/api";
import type {
  InterviewMode,
  InterviewDuration,
} from "@/lib/api/interview";

const PROJECT_FOCUSES: ReadonlyArray<{ value: string; label: string }> = [
  { value: "3ddepo-search", label: "3ddepo-search" },
  { value: "content orchestrator", label: "content orchestrator" },
  { value: "LearnDopamine", label: "LearnDopamine" },
  { value: "generic", label: "generic" },
];

const MODE_OPTIONS: ReadonlyArray<{
  value: InterviewMode;
  label: string;
  blurb: string;
}> = [
  {
    value: "behavioral",
    label: "Behavioral",
    blurb: "STAR stories from your own projects.",
  },
  {
    value: "technical",
    label: "Technical",
    blurb: "Design + tradeoff questions.",
  },
  {
    value: "code_defense",
    label: "Code defense",
    blurb: "Defend choices in your repo.",
  },
  {
    value: "mixed",
    label: "Mixed (40/40/20)",
    blurb: "Behavioral + technical + defense.",
  },
];

const DURATION_OPTIONS: ReadonlyArray<{
  value: InterviewDuration;
  label: string;
  turns: number;
  minutes: string;
  primary?: boolean;
}> = [
  { value: "quick", label: "Quick", turns: 3, minutes: "~8 min", primary: true },
  { value: "standard", label: "Standard", turns: 10, minutes: "~18 min" },
  { value: "deep", label: "Deep", turns: 15, minutes: "~30 min" },
];

interface ContentEmptyError {
  error: "content_empty";
  cta_url?: string;
  detail?: string;
}

/** Try to coerce a backend 400 payload into the `content_empty` shape. */
function parseContentEmpty(detail: string | undefined): ContentEmptyError | null {
  if (!detail) return null;
  // Backend may put either a raw string ("content_empty. Fill 2 stories at /content/...")
  // or a JSON blob in `detail`. Handle both.
  try {
    const parsed = JSON.parse(detail) as Record<string, unknown>;
    if (parsed && parsed.error === "content_empty") {
      return {
        error: "content_empty",
        cta_url: (parsed.cta_url as string) ?? undefined,
        detail: (parsed.detail as string) ?? undefined,
      };
    }
  } catch {
    /* fall through to string match */
  }
  if (detail.includes("content_empty")) {
    return { error: "content_empty", detail };
  }
  return null;
}

export default function InterviewStartPage() {
  const router = useRouter();
  const [projectFocus, setProjectFocus] = useState<string>(PROJECT_FOCUSES[0].value);
  const [mode, setMode] = useState<InterviewMode>("mixed");
  const [duration, setDuration] = useState<InterviewDuration>("quick");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contentEmpty, setContentEmpty] = useState<ContentEmptyError | null>(null);

  const submit = useCallback(async () => {
    setSubmitting(true);
    setError(null);
    setContentEmpty(null);
    try {
      const res = await startInterview({
        project_focus: projectFocus,
        mode,
        duration,
      });
      router.push(`/interview/${res.session_id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        const empty = parseContentEmpty(err.detail ?? err.message);
        if (empty) {
          setContentEmpty(empty);
          setSubmitting(false);
          return;
        }
      }
      setError(
        err instanceof Error ? err.message : "Failed to start interview.",
      );
      setSubmitting(false);
    }
  }, [projectFocus, mode, duration, router]);

  return (
    <div className="min-h-screen bg-background p-6">
      <div className="mx-auto flex w-full max-w-xl flex-col gap-6">
        <header className="flex flex-col gap-1">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            Interview drill
          </h1>
          <p className="text-sm text-muted-foreground">
            Grounded in your own STAR stories + code-defense notes. Grader
            gives 1-5 on 4 dims per answer.
          </p>
        </header>

        {/* Project focus */}
        <section className="flex flex-col gap-2">
          <label
            htmlFor="interview-project-focus"
            className="text-sm font-medium text-foreground"
          >
            Project focus
          </label>
          <select
            id="interview-project-focus"
            data-testid="interview-project-focus"
            value={projectFocus}
            onChange={(e) => setProjectFocus(e.target.value)}
            className="h-10 rounded-lg border border-border bg-card px-3 text-sm text-foreground"
          >
            {PROJECT_FOCUSES.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </section>

        {/* Mode */}
        <section className="flex flex-col gap-2">
          <p className="text-sm font-medium text-foreground">Mode</p>
          <div
            role="radiogroup"
            aria-label="Interview mode"
            className="grid grid-cols-1 gap-2 sm:grid-cols-2"
          >
            {MODE_OPTIONS.map((m) => {
              const active = mode === m.value;
              return (
                <button
                  key={m.value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  data-testid={`interview-mode-${m.value}`}
                  data-active={active ? "1" : "0"}
                  onClick={() => setMode(m.value)}
                  className={`flex flex-col items-start gap-0.5 rounded-lg border p-3 text-left transition-colors ${
                    active
                      ? "border-brand bg-brand-muted"
                      : "border-border bg-card hover:border-brand"
                  }`}
                >
                  <span className="text-sm font-semibold text-foreground">
                    {m.label}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {m.blurb}
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        {/* Duration */}
        <section className="flex flex-col gap-2">
          <p className="text-sm font-medium text-foreground">Duration</p>
          <div
            role="radiogroup"
            aria-label="Interview duration"
            className="grid grid-cols-1 gap-2 sm:grid-cols-3"
          >
            {DURATION_OPTIONS.map((d) => {
              const active = duration === d.value;
              return (
                <button
                  key={d.value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  data-testid={`interview-duration-${d.value}`}
                  data-active={active ? "1" : "0"}
                  onClick={() => setDuration(d.value)}
                  className={`flex flex-col items-start gap-0.5 rounded-lg border p-3 text-left transition-colors ${
                    active
                      ? "border-brand bg-brand-muted"
                      : d.primary
                      ? "border-brand/50 bg-card hover:border-brand"
                      : "border-border bg-card hover:border-brand"
                  }`}
                >
                  <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    {d.label}
                    {d.primary && !active && (
                      <span className="rounded bg-brand-muted px-1.5 py-0.5 text-[10px] uppercase text-brand">
                        default
                      </span>
                    )}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {d.turns}Q · {d.minutes}
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        {/* content_empty banner */}
        {contentEmpty && (
          <div
            data-testid="interview-content-empty"
            role="alert"
            className="flex items-start gap-3 rounded-lg border border-amber-300/60 bg-amber-50/80 px-4 py-3 text-amber-950"
          >
            <AlertCircle className="mt-0.5 size-4 shrink-0 text-amber-600" />
            <div className="flex flex-1 flex-col gap-1 text-sm">
              <p className="font-semibold">Fill more STAR stories first</p>
              <p className="text-xs text-amber-900/80">
                {contentEmpty.detail ??
                  "Behavioral and mixed modes need ≥2 filled stories. Add a couple, then come back."}
              </p>
              {contentEmpty.cta_url && (
                <Link
                  href={contentEmpty.cta_url}
                  data-testid="interview-content-empty-cta"
                  className="mt-1 inline-block text-xs font-medium text-amber-700 underline hover:text-amber-900"
                >
                  Open star_stories.md
                </Link>
              )}
            </div>
          </div>
        )}

        {error && !contentEmpty && (
          <div
            data-testid="interview-start-error"
            role="alert"
            className="flex items-start gap-3 rounded-lg border border-red-300/60 bg-red-50/80 px-4 py-3 text-sm text-red-950"
          >
            <AlertCircle className="mt-0.5 size-4 shrink-0 text-red-600" />
            <span>{error}</span>
          </div>
        )}

        {/* Submit */}
        <button
          type="button"
          data-testid="interview-start-submit"
          onClick={submit}
          disabled={submitting}
          className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-brand px-5 font-semibold text-brand-foreground hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <ArrowRight className="size-4" />
          )}
          {submitting ? "Starting..." : "Start interview"}
        </button>
      </div>
    </div>
  );
}
