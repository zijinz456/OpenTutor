"use client";

/**
 * `/session/daily` — the ADHD daily session runner (Phase 13 T5).
 *
 * Reads the card batch seeded by `<DailySessionCTA>` out of the
 * `daily-session` Zustand store, dispatches on `question_type`, and
 * drives the through-line: answer → feedback → auto-advance → closure.
 *
 * Renderer reuse
 * --------------
 * We deliberately do NOT reuse `<QuizView>` here. Quiz-view is tightly
 * coupled to a single course context (wrong-answers block, workspace
 * layout rewrites, feature-unlock tracking, quiz persistence) — the
 * ADHD flow is cross-course, ephemeral, and must not mutate workspace
 * state. Instead we reuse the smaller children quiz-view also uses
 * (`<QuizOptions>`, `<CodeExerciseBlock>`, `<LabExerciseBlock>`) so the
 * card body looks identical without inheriting the coupling.
 *
 * Direct-navigation guard
 * -----------------------
 * If the user opens `/session/daily` directly (shared URL, stale tab,
 * refresh after closure) the store is empty — we replace to `/` so they
 * land on the CTA instead of an empty shell.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useBadDayStore } from "@/store/bad-day";
import { useDailySessionStore } from "@/store/daily-session";
import {
  submitAnswer,
  type AnswerResult,
  type DailyPlanCard,
  type DailySessionSize,
  getDailyPlan,
} from "@/lib/api";
import { QuizOptions } from "@/components/sections/practice/quiz-options";
import { QuizResult } from "@/components/sections/practice/quiz-result";
import {
  CodeExerciseBlock,
  type CodeExerciseSubmitPayload,
  type CodeExerciseSubmitResult,
} from "@/components/blocks/code-exercise-block";
import { TraceBlock } from "@/components/blocks/trace-block";
import { ApplyBlock } from "@/components/blocks/apply-block";
import { CompareBlock } from "@/components/blocks/compare-block";
import { RebuildBlock } from "@/components/blocks/rebuild-block";
import {
  LabExerciseBlock,
  type LabExerciseSubmitPayload,
  type LabExerciseSubmitResult,
} from "@/components/blocks/lab-exercise-block";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { SessionClosure } from "@/components/session/session-closure";

const ADVANCE_DELAY_MS = 500;

/** Narrow metadata for code_exercise cards — same guard shape as
 *  `components/sections/practice/quiz-view.tsx` so we never leak the
 *  server-held `expected_output` to the client. */
function readCodeMeta(meta: Record<string, unknown> | null | undefined) {
  if (!meta) return { starterCode: "", hints: [] as string[] };
  const starterCode =
    typeof meta.starter_code === "string" ? meta.starter_code : "";
  const hints = Array.isArray(meta.hints)
    ? meta.hints.filter((h): h is string => typeof h === "string")
    : [];
  return { starterCode, hints };
}

/** Narrow metadata for lab_exercise cards — mirrors the quiz-view guard.
 *  `verification_rubric` stays server-side. */
function readLabMeta(meta: Record<string, unknown> | null | undefined) {
  if (!meta) return { target_url: "", hints: [] as string[] };
  const target_url = typeof meta.target_url === "string" ? meta.target_url : "";
  const category =
    typeof meta.category === "string" ? meta.category : undefined;
  const rawDiff = meta.difficulty;
  const difficulty: "easy" | "medium" | "hard" | undefined =
    rawDiff === "easy" || rawDiff === "medium" || rawDiff === "hard"
      ? rawDiff
      : undefined;
  const hints = Array.isArray(meta.hints)
    ? meta.hints.filter((h): h is string => typeof h === "string")
    : [];
  return { target_url, category, difficulty, hints };
}

function readDrillEditorMeta(meta: Record<string, unknown> | null | undefined) {
  if (!meta) return { starterCode: "", language: "python" };
  const starterCode =
    typeof meta.starter_code === "string" ? meta.starter_code : "";
  const language = typeof meta.language === "string" ? meta.language : "python";
  return { starterCode, language };
}

export default function DailySessionPage() {
  const router = useRouter();
  const cards = useDailySessionStore((s) => s.cards);
  const currentIdx = useDailySessionStore((s) => s.currentIdx);
  const size = useDailySessionStore((s) => s.size);
  const finished = useDailySessionStore((s) => s.finished);
  const answered = useDailySessionStore((s) => s.answered);
  const stats = useDailySessionStore((s) => s.stats);
  const recordAnswer = useDailySessionStore((s) => s.recordAnswer);
  const advance = useDailySessionStore((s) => s.advance);
  const start = useDailySessionStore((s) => s.start);
  const badDayActive = useBadDayStore((s) => s.isActiveToday());

  const [result, setResult] = useState<AnswerResult | null>(null);
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const questionStartRef = useRef(Date.now());
  const advanceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Direct-nav guard — bail to dashboard if store is empty. `useEffect` so
  // we don't call router.replace during render (Next.js warns against it).
  useEffect(() => {
    if (cards.length === 0 && !finished) {
      router.replace("/");
    }
  }, [cards.length, finished, router]);

  // Reset transient UI state when the cursor moves to a fresh card.
  useEffect(() => {
    setResult(null);
    setSelectedOption(null);
    setSubmitError(null);
    questionStartRef.current = Date.now();
  }, [currentIdx]);

  useEffect(
    () => () => {
      if (advanceTimerRef.current) clearTimeout(advanceTimerRef.current);
    },
    [],
  );

  const card: DailyPlanCard | undefined = cards[currentIdx];

  const scheduleAdvance = useCallback(() => {
    if (advanceTimerRef.current) clearTimeout(advanceTimerRef.current);
    advanceTimerRef.current = setTimeout(() => {
      advance();
    }, ADVANCE_DELAY_MS);
  }, [advance]);

  const handleMcSubmit = useCallback(
    async (option: string) => {
      if (!card || submitting || result) return;
      setSelectedOption(option);
      setSubmitting(true);
      setSubmitError(null);
      try {
        const elapsed = Date.now() - questionStartRef.current;
        const res = await submitAnswer(card.id, option, elapsed);
        setResult(res);
        recordAnswer(res.is_correct);
        scheduleAdvance();
      } catch {
        setSelectedOption(null);
        setSubmitError("Could not submit your answer. Please try again.");
      } finally {
        setSubmitting(false);
      }
    },
    [card, recordAnswer, result, scheduleAdvance, submitting],
  );

  const handleCodeSubmit = useCallback(
    async (
      problemId: string,
      payload: CodeExerciseSubmitPayload,
    ): Promise<CodeExerciseSubmitResult> => {
      const elapsed = Date.now() - questionStartRef.current;
      const res = await submitAnswer(problemId, JSON.stringify(payload), elapsed);
      recordAnswer(res.is_correct);
      scheduleAdvance();
      return {
        is_correct: res.is_correct,
        explanation: res.explanation ?? undefined,
      };
    },
    [recordAnswer, scheduleAdvance],
  );

  const handleLabSubmit = useCallback(
    async (
      problemId: string,
      payload: LabExerciseSubmitPayload,
    ): Promise<LabExerciseSubmitResult> => {
      const elapsed = Date.now() - questionStartRef.current;
      const res = await submitAnswer(problemId, JSON.stringify(payload), elapsed);
      recordAnswer(res.is_correct);
      scheduleAdvance();
      return {
        is_correct: res.is_correct,
        explanation: res.explanation ?? undefined,
      };
    },
    [recordAnswer, scheduleAdvance],
  );

  const handleDrillSubmit = useCallback(
    async (problemId: string, userAnswer: string): Promise<AnswerResult> => {
      const elapsed = Date.now() - questionStartRef.current;
      const res = await submitAnswer(problemId, userAnswer, elapsed);
      recordAnswer(res.is_correct);
      scheduleAdvance();
      return res;
    },
    [recordAnswer, scheduleAdvance],
  );

  const handleDoOneMore = useCallback(async () => {
    try {
      const plan = badDayActive
        ? await getDailyPlan(1 as DailySessionSize, { strategy: "easy_only" })
        : await getDailyPlan(1 as DailySessionSize);
      if (plan.cards.length === 0) {
        // Graceful: nothing left — go home instead of spinning.
        router.replace("/");
        return;
      }
      start(1, plan.cards);
    } catch {
      // Silent fallback — bail home, consistent with direct-nav guard.
      router.replace("/");
    }
  }, [badDayActive, router, start]);

  const optionKeys = useMemo(
    () => (card?.options ? Object.keys(card.options).sort() : []),
    [card],
  );

  // Closure screen wins whenever the session is done, even before the
  // advance timer runs — §8: user sees closure as soon as they've done N.
  if (finished) {
    return (
      <div className="min-h-screen bg-background py-12 px-4">
        <SessionClosure
          correct={stats.correct}
          total={answered}
          onBack={() => router.push("/")}
          onDoOneMore={() => void handleDoOneMore()}
        />
      </div>
    );
  }

  if (!card) {
    // Fallback render while the direct-nav guard redirects.
    return (
      <div className="min-h-screen bg-background" data-testid="daily-session-empty" />
    );
  }

  const meta = (card.problem_metadata ?? {}) as Record<string, unknown>;

  return (
    <div className="min-h-screen bg-background py-8 px-4">
      <div className="mx-auto max-w-xl space-y-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="outline">
            {Math.min(currentIdx + 1, size)} / {Math.min(size, cards.length)}
          </Badge>
          {card.difficulty_layer ? (
            <Badge variant="outline">Layer {card.difficulty_layer}</Badge>
          ) : null}
        </div>

        <p
          id="quiz-question-text"
          className="text-base font-medium leading-relaxed"
          data-testid="daily-session-question"
        >
          {card.question}
        </p>

        {card.question_type === "lab_exercise"
          ? (() => {
              const { target_url, category, difficulty, hints } =
                readLabMeta(meta);
              if (!target_url) {
                return (
                  <p role="alert" className="text-xs text-destructive">
                    Lab target URL missing from card metadata — skipping.
                  </p>
                );
              }
              return (
                <LabExerciseBlock
                  key={card.id}
                  problemId={card.id}
                  questionText={card.question}
                  targetUrl={target_url}
                  category={category}
                  difficulty={difficulty}
                  hints={hints}
                  onSubmit={(payload) => handleLabSubmit(card.id, payload)}
                />
              );
            })()
          : card.question_type === "code_exercise"
            ? (() => {
                const { starterCode, hints } = readCodeMeta(meta);
                return (
                  <CodeExerciseBlock
                    key={card.id}
                    problemId={card.id}
                    starterCode={starterCode}
                    questionText={card.question}
                    hints={hints}
                    onSubmit={(payload) => handleCodeSubmit(card.id, payload)}
                  />
                );
              })()
            : card.question_type === "trace"
              ? (
                  <TraceBlock
                    key={card.id}
                    problemId={card.id}
                    questionText={card.question}
                    correctAnswer={card.correct_answer}
                    onSubmit={(answer) => handleDrillSubmit(card.id, answer)}
                  />
                )
              : card.question_type === "apply"
                ? (() => {
                    const { starterCode, language } = readDrillEditorMeta(meta);
                    return (
                      <ApplyBlock
                        key={card.id}
                        problemId={card.id}
                        questionText={card.question}
                        starterCode={starterCode}
                        language={language}
                        correctAnswer={card.correct_answer}
                        onSubmit={(answer) => handleDrillSubmit(card.id, answer)}
                      />
                    );
                  })()
                : card.question_type === "compare"
                  ? (
                      <CompareBlock
                        key={card.id}
                        problemId={card.id}
                        questionText={card.question}
                        options={card.options}
                        correctAnswer={card.correct_answer}
                        onSubmit={(answer) => handleDrillSubmit(card.id, answer)}
                      />
                    )
                  : card.question_type === "rebuild"
                    ? (() => {
                        const { starterCode, language } =
                          readDrillEditorMeta(meta);
                        return (
                          <RebuildBlock
                            key={card.id}
                            problemId={card.id}
                            questionText={card.question}
                            starterCode={starterCode}
                            language={language}
                            correctAnswer={card.correct_answer}
                            onSubmit={(answer) =>
                              handleDrillSubmit(card.id, answer)
                            }
                          />
                        );
                      })()
            : (
                <QuizOptions
                  optionKeys={optionKeys}
                  options={(card.options ?? {}) as Record<string, string>}
                  selectedOption={selectedOption}
                  result={result}
                  submitting={submitting}
                  onOptionClick={(key) => void handleMcSubmit(key)}
                />
              )}

        {submitError && (
          <p role="alert" className="text-xs text-destructive">
            {submitError}
          </p>
        )}

        {result ? <QuizResult result={result} /> : null}

        <div className="flex justify-end">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => router.push("/")}
            data-testid="daily-session-exit"
          >
            Exit
          </Button>
        </div>
      </div>
    </div>
  );
}
