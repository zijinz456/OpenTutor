"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useT } from "@/lib/i18n-context";
import {
  extractQuiz,
  listProblems,
  submitAnswer,
  type QuizProblem,
  type AnswerResult,
} from "@/lib/api";
import { useWorkspaceStore } from "@/store/workspace";
import type { BlockType } from "@/lib/block-system/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AiFeatureBlocked } from "@/components/shared/ai-feature-blocked";
import { updateUnlockContext, getUnlockContext } from "@/lib/block-system/feature-unlock";

interface QuizViewProps {
  courseId: string;
  aiActionsEnabled?: boolean;
  modeHint?: "course_following" | "self_paced" | "exam_prep" | "maintenance";
  difficultyHint?: "easy" | "medium" | "hard";
}

function layerBadgeClass(layer: number): string {
  if (layer >= 3) return "bg-destructive/10 text-destructive";
  if (layer === 2) return "bg-warning/10 text-warning";
  return "bg-success/10 text-success";
}

export function QuizView({
  courseId,
  aiActionsEnabled = true,
  modeHint,
  difficultyHint,
}: QuizViewProps) {
  const t = useT();
  const refreshKey = useWorkspaceStore((s) => s.sectionRefreshKey["practice"]);
  const [problems, setProblems] = useState<QuizProblem[]>([]);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractStatus, setExtractStatus] = useState<string | null>(null);
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [score, setScore] = useState({ correct: 0, total: 0 });
  const consecutiveWrongRef = useRef(0);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const items = await listProblems(courseId);
      setProblems(items);
    } catch {
      setProblems([]);
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    void fetchData();
  }, [fetchData, refreshKey]);

  useEffect(() => {
    setSelectedOption(null);
    setResult(null);
  }, [currentIdx]);

  const handleExtract = async () => {
    setExtracting(true);
    setExtractStatus(null);
    try {
      const layoutMode = useWorkspaceStore.getState().spaceLayout.mode ?? undefined;
      const mode = modeHint ?? layoutMode;
      const res = await extractQuiz(courseId, undefined, mode, difficultyHint);
      setExtractStatus(t("quiz.extract.success").replace("{count}", String(res.problems_created)));
      await fetchData();
    } catch (error) {
      const message = (error as Error).message;
      setExtractStatus(`${t("quiz.extract.failed")} ${message}`);
    } finally {
      setExtracting(false);
    }
  };

  const handleOptionClick = async (option: string) => {
    if (result || submitting) return;
    setSubmitError(null);
    setSelectedOption(option);
    setSubmitting(true);
    try {
      const res = await submitAnswer(problems[currentIdx].id, option);
      setResult(res);
      setScore((prev) => ({
        correct: prev.correct + (res.is_correct ? 1 : 0),
        total: prev.total + 1,
      }));
      // Track feature-unlock context
      const ctx = getUnlockContext(courseId, 0);
      updateUnlockContext(courseId, {
        practiceAttempts: ctx.practiceAttempts + 1,
        hasWrongAnswer: ctx.hasWrongAnswer || !res.is_correct,
      });
      // Track consecutive wrong answers to surface wrong_answers block
      if (!res.is_correct) {
        consecutiveWrongRef.current += 1;
        if (consecutiveWrongRef.current >= 3) {
          const store = useWorkspaceStore.getState();
          const blocks = store.spaceLayout.blocks;
          const hasWrongAnswersBlock = blocks.some(b => b.type === "wrong_answers");
          if (!hasWrongAnswersBlock) {
            store.addBlock("wrong_answers", {}, "agent");
          } else {
            // Move wrong_answers to front by reordering
            const wrongFirst = ["wrong_answers", ...blocks.filter(b => b.type !== "wrong_answers").map(b => b.type)];
            store.reorderBlocks(wrongFirst as BlockType[]);
          }
          consecutiveWrongRef.current = 0;
        }
      } else {
        consecutiveWrongRef.current = 0;
      }
    } catch {
      setSelectedOption(null);
      setSubmitError(t("quiz.submitFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8" data-testid="quiz-panel">
        <div className="h-4 w-32 bg-muted animate-pulse rounded" />
      </div>
    );
  }

  if (problems.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center" data-testid="quiz-panel">
        <h3 className="text-sm font-medium mb-1">{t("quiz.title")}</h3>
        <p className="text-xs text-muted-foreground max-w-xs">{t("quiz.empty")}</p>
        {!aiActionsEnabled ? <AiFeatureBlocked compact className="mt-3 w-full max-w-sm text-left" /> : null}
        <Button className="mt-3" size="sm" onClick={() => void handleExtract()} disabled={!aiActionsEnabled || extracting}>
          {extracting ? `${t("quiz.generating")}...` : t("quiz.generate")}
        </Button>
        {extractStatus ? (
          <p className="mt-3 text-xs text-muted-foreground" data-testid="quiz-extract-status">
            {extractStatus}
          </p>
        ) : null}
      </div>
    );
  }

  const problem = problems[currentIdx];
  const optionKeys = problem.options ? Object.keys(problem.options).sort() : [];
  const accuracy = score.total > 0 ? Math.round((score.correct / score.total) * 100) : null;
  const difficultyLayer = problem.difficulty_layer ?? null;
  const metadata = (problem.problem_metadata ?? {}) as Record<string, unknown>;
  const coreConcept = typeof metadata.core_concept === "string" ? metadata.core_concept : null;
  const bloomLevel = typeof metadata.bloom_level === "string" ? metadata.bloom_level : null;

  const optionStyle = (key: string) => {
    if (!result) {
      return key === selectedOption
        ? "border-primary bg-primary/10"
        : "border-border hover:border-primary/50";
    }
    if (key === result.correct_answer) return "border-green-500 bg-green-500/10";
    if (key === selectedOption && !result.is_correct) {
      return "border-destructive bg-destructive/10";
    }
    return "border-border opacity-60";
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-testid="quiz-panel">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/60 shrink-0">
        {accuracy !== null ? <Badge variant="outline">{accuracy}%</Badge> : null}
        <span className="ml-auto text-xs text-muted-foreground">
          {t("quiz.question")} {currentIdx + 1} {t("quiz.of")} {problems.length}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-4">
        <div className="flex flex-wrap items-center gap-1.5">
          {difficultyHint ? (
            <Badge variant="outline" className="text-[10px]">
              {t("quiz.strategy")}: {t(`quiz.difficulty.${difficultyHint}`)}
            </Badge>
          ) : null}
          {difficultyLayer ? (
            <Badge variant="outline" className={`text-[10px] ${layerBadgeClass(difficultyLayer)}`}>
              {t("quiz.layer").replace("{layer}", String(difficultyLayer))}
            </Badge>
          ) : null}
          {coreConcept ? (
            <Badge variant="outline" className="text-[10px]">
              {coreConcept}
            </Badge>
          ) : null}
          {bloomLevel ? (
            <Badge variant="outline" className="text-[10px]">
              {t("quiz.bloom").replace("{level}", bloomLevel)}
            </Badge>
          ) : null}
        </div>

        <p className="text-sm font-medium leading-relaxed" data-testid="quiz-question">
          {problem.question}
        </p>

        <div className="space-y-3" role="radiogroup" aria-label="Answer options">
          {optionKeys.map((key) => (
            <button
              key={key}
              role="radio"
              aria-checked={selectedOption === key}
              data-testid={`quiz-option-${key}`}
              disabled={!!result || submitting}
              onClick={() => void handleOptionClick(key)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  if (!result && !submitting) void handleOptionClick(key);
                }
              }}
              className={`w-full text-left rounded-xl border px-3.5 py-3 text-sm min-h-[44px] transition-colors ${optionStyle(key)} disabled:cursor-default`}
            >
              <span className="font-medium mr-2">{key.toUpperCase()}.</span>
              {problem.options?.[key]}
            </button>
          ))}
        </div>

        {submitError && (
          <p className="text-xs text-destructive mt-2">{submitError}</p>
        )}

        {result?.explanation ? (
          <div className="space-y-1.5 pt-1" aria-live="assertive">
            <Badge variant={result.is_correct ? "default" : "destructive"}>
              {result.is_correct ? t("quiz.correct") : result.correct_answer?.toUpperCase()}
            </Badge>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {t("quiz.explanation")} {result.explanation}
            </p>
          </div>
        ) : null}

        {result?.prerequisite_gaps && result.prerequisite_gaps.length > 0 ? (
          <div className="rounded-2xl border border-warning/30 bg-warning-muted/20 p-3.5 space-y-2">
            <p className="text-xs font-semibold text-warning">
              {t("quiz.prerequisiteGaps") !== "quiz.prerequisiteGaps"
                ? t("quiz.prerequisiteGaps")
                : "Prerequisite gaps detected"}
            </p>
            <div className="space-y-1.5">
              {result.prerequisite_gaps.map((gap) => (
                <div key={gap.concept_id} className="flex items-center justify-between text-xs">
                  <span className="text-foreground">{gap.concept}</span>
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full bg-warning rounded-full"
                        style={{ width: `${Math.round(gap.mastery * 100)}%` }}
                      />
                    </div>
                    <span className="text-muted-foreground w-8 text-right">{Math.round(gap.mastery * 100)}%</span>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-muted-foreground">
              {t("quiz.prerequisiteHint") !== "quiz.prerequisiteHint"
                ? t("quiz.prerequisiteHint")
                : "Strengthen these foundational concepts to improve your understanding."}
            </p>
          </div>
        ) : null}
      </div>

      <div className="flex items-center justify-between px-3 py-2 border-t border-border/60 shrink-0">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={currentIdx === 0}
          onClick={() => setCurrentIdx((i) => i - 1)}
        >
          {t("quiz.prev")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={currentIdx >= problems.length - 1}
          onClick={() => setCurrentIdx((i) => i + 1)}
        >
          {t("quiz.next")}
        </Button>
      </div>
    </div>
  );
}
