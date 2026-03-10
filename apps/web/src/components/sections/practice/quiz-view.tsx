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
import { QuizOptions } from "./quiz-options";
import { QuizResult } from "./quiz-result";

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
  const questionStartTimeRef = useRef(Date.now());

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
    questionStartTimeRef.current = Date.now();
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
      const answerTimeMs = Date.now() - questionStartTimeRef.current;
      const res = await submitAnswer(problems[currentIdx].id, option, answerTimeMs);
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
      <div className="flex-1 flex items-center justify-center p-8" data-testid="quiz-panel" role="status" aria-live="polite">
        <div className="h-4 w-32 bg-muted animate-pulse rounded" aria-label="Loading quiz" />
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
          <p role="status" aria-live="polite" className="mt-3 text-xs text-muted-foreground" data-testid="quiz-extract-status">
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

  return (
    <div role="form" aria-label="Quiz question" className="flex-1 flex flex-col overflow-hidden" data-testid="quiz-panel">
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

        <p id="quiz-question-text" className="text-sm font-medium leading-relaxed" data-testid="quiz-question">
          {problem.question}
        </p>

        <QuizOptions
          optionKeys={optionKeys}
          options={problem.options ?? {}}
          selectedOption={selectedOption}
          result={result}
          submitting={submitting}
          onOptionClick={handleOptionClick}
        />

        {submitError && (
          <p role="alert" className="text-xs text-destructive mt-2">{submitError}</p>
        )}

        {result ? <QuizResult result={result} /> : null}
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
