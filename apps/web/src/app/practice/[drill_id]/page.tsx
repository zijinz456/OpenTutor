"use client";

/**
 * `/practice/[drill_id]` — the drill runner (Phase 16c T9, MVP).
 *
 * Loads one :type:`DrillOut`, pre-fills the editor with ``starter_code``,
 * and on submit calls ``POST /api/drills/{id}/submit``. The result
 * renders as an ADHD-safe banner: green on pass, amber (NOT red) on
 * fail, with the raw runner output tucked inside a `<details>` block so
 * the default view isn't a wall of pytest traceback.
 *
 * Editor choice
 * -------------
 * Phase 16c is MVP. The repo ships no Monaco / CodeMirror wrapper under
 * ``src/components/`` that fits a drill runner, and pulling a new heavy
 * dep just for this slice is explicitly out of scope. We use a plain
 * monospace `<textarea>` with tab-to-indent behaviour — good enough for
 * the practice loop. A later pass can swap in a proper editor without
 * changing the API surface.
 *
 * Hints progressive reveal
 * ------------------------
 * All hints are fetched up-front (the backend ships them inline) but we
 * only render them on explicit "Need a hint?" clicks, one at a time.
 * This mirrors the "don't overwhelm" discipline — ADHD learners who
 * don't click never see them.
 *
 * Skip semantics
 * --------------
 * "Skip — ADHD is fine" does NOT submit. It fetches the next unpassed
 * drill via ``getNextDrill`` and routes there; if the course is done it
 * routes back to `/courses`.
 */

import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type KeyboardEvent,
} from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, CheckCircle2, AlertCircle } from "lucide-react";
import {
  ApiError,
  getDrill,
  submitDrill,
  type DrillOut,
  type DrillSubmitResult,
} from "@/lib/api";

/**
 * Course slug inference from a drill.
 *
 * The drill payload doesn't embed its course slug; to route "Skip" we'd
 * ideally have that. The fallback: after submit we get
 * ``next_drill_id`` directly; skip without submit falls back to routing
 * to `/courses` when we can't resolve the next drill from the TOC we
 * never loaded. For MVP we accept that "Skip" without a known course
 * slug routes back to `/courses` — the user still has forward motion.
 */

function PracticeContent() {
  const params = useParams();
  const router = useRouter();
  const drillIdParam = params?.drill_id;
  const drillId = Array.isArray(drillIdParam) ? drillIdParam[0] : drillIdParam;

  const [drill, setDrill] = useState<DrillOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const [code, setCode] = useState<string>("");
  const [revealedHints, setRevealedHints] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<DrillSubmitResult | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!drillId) return () => {};
    setLoading(true);
    setError(null);
    setNotFound(false);
    setResult(null);
    setRevealedHints(0);
    let cancelled = false;
    getDrill(drillId)
      .then((res) => {
        if (cancelled) return;
        setDrill(res);
        setCode(res.starter_code);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setError("Не вдалось завантажити — спробуй ще раз");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [drillId]);

  useEffect(() => {
    const cancel = load();
    return cancel;
  }, [load]);

  const onSubmit = useCallback(async () => {
    if (!drill) return;
    setSubmitting(true);
    setSubmitError(null);
    setResult(null);
    try {
      const res = await submitDrill(drill.id, code);
      setResult(res);
    } catch {
      setSubmitError("Не вдалось надіслати — спробуй ще раз");
    } finally {
      setSubmitting(false);
    }
  }, [drill, code]);

  const onSkip = useCallback(async () => {
    // Skip without submitting. We don't know the course slug from the
    // drill payload, so the forward route is a best-effort: if the user
    // already submitted (result present) we use next_drill_id; else we
    // route back to the course list. Either way the user has motion.
    if (result?.next_drill_id) {
      router.push(`/practice/${result.next_drill_id}`);
      return;
    }
    router.push("/courses");
  }, [result, router]);

  const onTextareaKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      // Tab indent — otherwise Tab moves focus away from the editor.
      if (event.key !== "Tab") return;
      event.preventDefault();
      const target = event.currentTarget;
      const { selectionStart, selectionEnd, value } = target;
      const next =
        value.slice(0, selectionStart) + "    " + value.slice(selectionEnd);
      setCode(next);
      // Restore caret after the inserted spaces. React schedules the state
      // update async so we set selection after the value is re-applied.
      requestAnimationFrame(() => {
        target.selectionStart = selectionStart + 4;
        target.selectionEnd = selectionStart + 4;
      });
    },
    [],
  );

  const hintsRemaining = useMemo(
    () => (drill ? drill.hints.length - revealedHints : 0),
    [drill, revealedHints],
  );

  return (
    <div className="min-h-screen bg-background py-6 px-4">
      <div className="mx-auto max-w-5xl space-y-5">
        <div>
          <Link
            href="/courses"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="size-3.5" />
            До курсів
          </Link>
        </div>

        {loading && (
          <div className="space-y-3" data-testid="drill-loading">
            <div className="h-8 w-64 rounded bg-muted/40 animate-pulse" />
            <div className="h-4 w-full rounded bg-muted/40 animate-pulse" />
            <div className="h-64 rounded-xl bg-muted/40 animate-pulse" />
          </div>
        )}

        {!loading && notFound && (
          <div
            role="alert"
            data-testid="drill-not-found"
            className="rounded-2xl bg-muted/30 px-5 py-4 text-sm text-muted-foreground card-shadow"
          >
            <p>Дрила не існує.</p>
            <Link
              href="/courses"
              className="mt-2 inline-block text-xs text-foreground underline"
            >
              До списку курсів
            </Link>
          </div>
        )}

        {!loading && error && !notFound && (
          <div
            role="alert"
            data-testid="drill-error"
            className="rounded-2xl bg-destructive/5 px-5 py-4 text-sm text-destructive card-shadow"
          >
            <p>{error}</p>
            <button
              type="button"
              onClick={load}
              className="mt-2 rounded-full border border-destructive/40 bg-destructive/10 px-3 py-1 text-xs font-medium text-destructive hover:bg-destructive/20 transition-colors"
            >
              Спробувати ще раз
            </button>
          </div>
        )}

        {!loading && !error && !notFound && drill && (
          <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_280px]">
            {/* ── Main column ─────────────────────────────────────── */}
            <div className="space-y-4 min-w-0">
              <header className="space-y-2">
                <div className="flex items-start justify-between gap-3">
                  <h1 className="font-display text-xl font-semibold tracking-tight text-foreground md:text-2xl">
                    {drill.title}
                  </h1>
                  <span
                    data-testid="drill-time-budget"
                    className="shrink-0 rounded-full border border-border bg-muted/40 px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground"
                  >
                    ~{drill.time_budget_min} хв
                  </span>
                </div>
                <p
                  data-testid="drill-why-it-matters"
                  className="text-sm italic text-foreground/90"
                >
                  {drill.why_it_matters}
                </p>
                <p
                  data-testid="drill-source-citation"
                  className="text-[11px] text-muted-foreground"
                >
                  {drill.source_citation}
                </p>
              </header>

              <div className="rounded-xl bg-card card-shadow">
                <label
                  htmlFor="drill-code-editor"
                  className="block px-4 pt-3 text-[11px] font-medium text-muted-foreground"
                >
                  Код
                </label>
                <textarea
                  id="drill-code-editor"
                  data-testid="drill-code-editor"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  onKeyDown={onTextareaKeyDown}
                  spellCheck={false}
                  className="w-full min-h-[320px] bg-transparent px-4 py-3 font-mono text-[13px] leading-relaxed text-foreground outline-none resize-y"
                />
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onSubmit}
                  disabled={submitting}
                  data-testid="drill-submit"
                  className="h-10 px-5 bg-brand text-brand-foreground rounded-full text-sm font-medium hover:opacity-90 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {submitting ? "Запускаю…" : "Надіслати"}
                </button>
                <button
                  type="button"
                  onClick={onSkip}
                  data-testid="drill-skip"
                  className="h-10 px-4 rounded-full border border-border bg-card text-sm text-muted-foreground hover:bg-muted/30 transition-colors"
                >
                  Пропустити — це ок
                </button>
              </div>

              {submitError && (
                <div
                  role="alert"
                  data-testid="drill-submit-error"
                  className="rounded-xl bg-destructive/5 px-4 py-3 text-sm text-destructive card-shadow"
                >
                  {submitError}
                </div>
              )}

              {result && result.passed && (
                <div
                  role="status"
                  data-testid="drill-result-pass"
                  className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 card-shadow"
                >
                  <div className="flex items-start gap-2">
                    <CheckCircle2 className="size-5 shrink-0 text-emerald-600 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-emerald-700">
                        Пройдено
                      </p>
                      {result.feedback && (
                        <p className="mt-0.5 text-sm text-foreground/90">
                          {result.feedback}
                        </p>
                      )}
                      <div className="mt-3">
                        {result.next_drill_id ? (
                          <Link
                            href={`/practice/${result.next_drill_id}`}
                            className="inline-block rounded-full border border-emerald-500/50 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-500/20 transition-colors"
                          >
                            Наступний дрил
                          </Link>
                        ) : (
                          <div className="flex flex-col gap-1">
                            <p className="text-xs text-emerald-700">
                              Курс завершено.
                            </p>
                            <Link
                              href="/courses"
                              className="inline-block text-xs text-foreground underline"
                            >
                              До списку курсів
                            </Link>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {result && !result.passed && (
                <div
                  role="status"
                  data-testid="drill-result-fail"
                  className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 card-shadow"
                >
                  <div className="flex items-start gap-2">
                    <AlertCircle className="size-5 shrink-0 text-amber-600 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-amber-700">
                        Ще не зовсім
                      </p>
                      {result.feedback && (
                        <p className="mt-0.5 text-sm text-foreground/90">
                          {result.feedback}
                        </p>
                      )}
                      <details className="mt-3">
                        <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
                          Деталі запуску
                        </summary>
                        <pre
                          data-testid="drill-result-runner-output"
                          className="mt-2 overflow-x-auto rounded-lg bg-muted/30 p-3 text-[11px] leading-relaxed text-foreground/90 whitespace-pre-wrap"
                        >
                          {result.runner_output}
                        </pre>
                      </details>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* ── Side column: hints ──────────────────────────────── */}
            <aside className="space-y-3">
              <div className="rounded-xl bg-card p-4 card-shadow">
                <p className="text-xs font-semibold text-foreground">
                  Підказки
                </p>
                {drill.hints.length === 0 ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Для цього дрилу немає підказок.
                  </p>
                ) : (
                  <>
                    {revealedHints === 0 && (
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        Всього: {drill.hints.length}. Відкривай по одній,
                        коли дійсно потрібно.
                      </p>
                    )}

                    {revealedHints > 0 && (
                      <ol
                        data-testid="drill-hints-revealed"
                        className="mt-2 list-decimal list-inside space-y-2 text-sm text-foreground/90"
                      >
                        {drill.hints.slice(0, revealedHints).map((hint, i) => (
                          <li key={i}>{hint}</li>
                        ))}
                      </ol>
                    )}

                    {hintsRemaining > 0 && (
                      <button
                        type="button"
                        onClick={() =>
                          setRevealedHints((n) =>
                            Math.min(n + 1, drill.hints.length),
                          )
                        }
                        data-testid="drill-hints-reveal"
                        className="mt-3 w-full rounded-full border border-border bg-muted/30 px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted/50 transition-colors"
                      >
                        Потрібна підказка? ({hintsRemaining})
                      </button>
                    )}
                  </>
                )}
              </div>

              {drill.skill_tags.length > 0 && (
                <div className="rounded-xl bg-card p-4 card-shadow">
                  <p className="text-xs font-semibold text-foreground">
                    Навички
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {drill.skill_tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded-full bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </aside>
          </div>
        )}
      </div>
    </div>
  );
}

export default function PracticePage() {
  // Wrap in Suspense so ``useParams()`` satisfies Next 16's prerender
  // pass, mirroring the convention used by `/tracks/[slug]`.
  return (
    <Suspense fallback={<div className="min-h-screen bg-background" />}>
      <PracticeContent />
    </Suspense>
  );
}
