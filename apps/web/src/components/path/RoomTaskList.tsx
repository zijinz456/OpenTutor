"use client";

/**
 * `<RoomTaskList>` — room runner (Phase 16a T4).
 *
 * Renders every task inside a room as an inline, expandable card. Click
 * on a collapsed card reveals the block renderer appropriate for the
 * `question_type`; submit calls `submitAnswer()` and flips
 * `is_complete` optimistically.
 *
 * Dispatch table
 * --------------
 *   - `trace` / `apply` / `compare` / `rebuild` → reuse the existing
 *     block renderers from Phase 4bdc244.
 *   - `code_exercise` / `lab_exercise` → existing editor-backed blocks.
 *   - `mc` / `multiple_choice` → a small inline button grid (same
 *     semantics as `<QuizOptions>` but self-contained so we don't drag
 *     the i18n context in here).
 *   - `flashcard` / `tf` / `short_answer` → a free-text input with
 *     Submit; flashcard shows a reveal button first. These are
 *     intentionally simple — a full reuse of the practice renderers
 *     would pull in too much course-scoped machinery.
 *   - Anything else → a muted "Unsupported task type" row. The user
 *     can still mark the room done on adjacent tasks.
 *
 * Optimistic state
 * ----------------
 * We keep a local `completedIds` set mirroring the initial
 * `is_complete` flag from the server. On a correct submission we add
 * the task id; the room banner + per-task badge pick it up without a
 * refetch. If a submission fails (network / grading error) we do NOT
 * add to the set — the user can retry inline.
 */

import { useMemo, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import {
  submitAnswer,
  type AnswerResult,
  type RoomTask,
} from "@/lib/api";
import { ExplainStep } from "@/components/practice/explain-step";
import { MissBanner } from "@/components/practice/miss-banner";
import {
  CodeExerciseBlock,
  type CodeExerciseSubmitPayload,
  type CodeExerciseSubmitResult,
} from "@/components/blocks/code-exercise-block";
import {
  LabExerciseBlock,
  type LabExerciseSubmitPayload,
  type LabExerciseSubmitResult,
} from "@/components/blocks/lab-exercise-block";
import { TraceBlock } from "@/components/blocks/trace-block";
import { ApplyBlock } from "@/components/blocks/apply-block";
import { CompareBlock } from "@/components/blocks/compare-block";
import { RebuildBlock } from "@/components/blocks/rebuild-block";

interface RoomTaskListProps {
  tasks: RoomTask[];
  /** Invoked every time a task transitions to complete — parent uses
   *  this to bump the header counter without a network refetch. */
  onTaskComplete?: (taskId: string) => void;
}

export function RoomTaskList({ tasks, onTaskComplete }: RoomTaskListProps) {
  const initialComplete = useMemo(
    () => new Set(tasks.filter((t) => t.is_complete).map((t) => t.id)),
    [tasks],
  );
  const [completedIds, setCompletedIds] = useState<Set<string>>(initialComplete);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(
    () => new Set(tasks.filter((t) => !t.is_complete).map((t) => t.id)),
  );

  const markComplete = (taskId: string) => {
    setCompletedIds((prev) => {
      if (prev.has(taskId)) return prev;
      const next = new Set(prev);
      next.add(taskId);
      return next;
    });
    onTaskComplete?.(taskId);
  };

  const toggleExpanded = (taskId: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  };

  const allDone =
    tasks.length > 0 && tasks.every((t) => completedIds.has(t.id));

  return (
    <div className="space-y-3" data-testid="room-task-list">
      {tasks.map((task, idx) => {
        const isComplete = completedIds.has(task.id);
        const isExpanded = expandedIds.has(task.id);
        return (
          <TaskCard
            key={task.id}
            index={idx + 1}
            task={task}
            isComplete={isComplete}
            isExpanded={isExpanded}
            onToggle={() => toggleExpanded(task.id)}
            onCorrect={() => markComplete(task.id)}
          />
        );
      })}

      {allDone && (
        <div
          data-testid="room-task-list-banner"
          className="rounded-2xl border border-emerald-500/40 bg-emerald-500/10 p-5 text-center card-shadow"
        >
          <p className="text-sm font-semibold text-emerald-800">
            Room done 🎉
          </p>
        </div>
      )}
    </div>
  );
}

interface TaskCardProps {
  index: number;
  task: RoomTask;
  isComplete: boolean;
  isExpanded: boolean;
  onToggle: () => void;
  onCorrect: () => void;
}

function TaskCard({
  index,
  task,
  isComplete,
  isExpanded,
  onToggle,
  onCorrect,
}: TaskCardProps) {
  return (
    <section
      data-testid={`task-card-${task.id}`}
      data-complete={isComplete}
      className={`rounded-xl border ${
        isComplete
          ? "border-emerald-500/30 bg-emerald-500/5"
          : "border-border bg-card"
      } p-4 card-shadow`}
    >
      <button
        type="button"
        onClick={onToggle}
        data-testid={`task-card-header-${task.id}`}
        className="flex w-full items-start gap-3 text-left"
      >
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums pt-0.5">
          {String(index).padStart(2, "0")}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground line-clamp-2">
            {task.question}
          </p>
          <p className="mt-0.5 text-[11px] uppercase tracking-wide text-muted-foreground">
            {task.question_type.replace(/_/g, " ")}
            {task.difficulty_layer ? ` · L${task.difficulty_layer}` : ""}
          </p>
        </div>
        {isComplete && (
          <span
            data-testid={`task-card-done-${task.id}`}
            className="shrink-0 flex items-center gap-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[11px] font-medium text-emerald-700"
          >
            <Check className="size-3" />
            done
          </span>
        )}
        <ChevronDown
          className={`size-4 shrink-0 text-muted-foreground transition-transform ${
            isExpanded ? "rotate-180" : ""
          }`}
        />
      </button>

      {isExpanded && (
        <div className="mt-3" data-testid={`task-card-body-${task.id}`}>
          <TaskRenderer task={task} onCorrect={onCorrect} />
        </div>
      )}
    </section>
  );
}

/** Narrow metadata for code_exercise cards — mirror daily/session renderer. */
function readCodeMeta(meta: Record<string, unknown> | null | undefined) {
  if (!meta) return { starterCode: "", hints: [] as string[] };
  const starterCode =
    typeof meta.starter_code === "string" ? meta.starter_code : "";
  const hints = Array.isArray(meta.hints)
    ? meta.hints.filter((h): h is string => typeof h === "string")
    : [];
  return { starterCode, hints };
}

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

function readEditorMeta(meta: Record<string, unknown> | null | undefined) {
  if (!meta) return { starterCode: "", language: "python" };
  const starterCode =
    typeof meta.starter_code === "string" ? meta.starter_code : "";
  const language = typeof meta.language === "string" ? meta.language : "python";
  return { starterCode, language };
}

interface TaskRendererProps {
  task: RoomTask;
  onCorrect: () => void;
  /** Optional latch — fires after every submit roundtrip completes,
   *  regardless of correctness. Hosts (e.g. PythonPane) use this to
   *  show a "Next task" CTA after the user has engaged with the
   *  current task. Distinct from `onCorrect` (only correct submits).
   *  Undefined by default so existing call sites (room-page inline
   *  expandable list) don't need touching. */
  onAttempt?: () => void;
}

/**
 * Exported so the unit tests can drive the dispatch directly without
 * pulling in the collapse/expand wrapper. Not re-exported from any
 * barrel — keep it test-scoped.
 */
export function TaskRenderer({ task, onCorrect, onAttempt }: TaskRendererProps) {
  // The RoomTask schema never ships `problem_metadata`; editor tasks
  // that genuinely need `starter_code` will show an empty editor in
  // seed-gap scenarios. When Phase 16b adds metadata to the endpoint
  // we plug it in here without touching the call sites.
  const meta: Record<string, unknown> | null = null;

  const handleDrillSubmit = async (answer: string): Promise<AnswerResult> => {
    const res = await submitAnswer(task.id, answer);
    if (res.is_correct) onCorrect();
    onAttempt?.();
    return res;
  };

  const handleCodeSubmit = async (
    payload: CodeExerciseSubmitPayload,
  ): Promise<CodeExerciseSubmitResult> => {
    const res = await submitAnswer(task.id, JSON.stringify(payload));
    if (res.is_correct) onCorrect();
    onAttempt?.();
    return {
      is_correct: res.is_correct,
      explanation: res.explanation ?? undefined,
    };
  };

  const handleLabSubmit = async (
    payload: LabExerciseSubmitPayload,
  ): Promise<LabExerciseSubmitResult> => {
    const res = await submitAnswer(task.id, JSON.stringify(payload));
    if (res.is_correct) onCorrect();
    onAttempt?.();
    return {
      is_correct: res.is_correct,
      explanation: res.explanation ?? undefined,
    };
  };

  switch (task.question_type) {
    case "trace":
      return (
        <TraceBlock
          problemId={task.id}
          questionText={task.question}
          onSubmit={handleDrillSubmit}
        />
      );
    case "apply": {
      const { starterCode, language } = readEditorMeta(meta);
      return (
        <ApplyBlock
          problemId={task.id}
          questionText={task.question}
          starterCode={starterCode}
          language={language}
          onSubmit={handleDrillSubmit}
        />
      );
    }
    case "compare":
      return (
        <CompareBlock
          problemId={task.id}
          questionText={task.question}
          options={task.options}
          onSubmit={handleDrillSubmit}
        />
      );
    case "rebuild": {
      const { starterCode, language } = readEditorMeta(meta);
      return (
        <RebuildBlock
          problemId={task.id}
          questionText={task.question}
          starterCode={starterCode}
          language={language}
          onSubmit={handleDrillSubmit}
        />
      );
    }
    case "code_exercise": {
      const { starterCode, hints } = readCodeMeta(meta);
      return (
        <CodeExerciseBlock
          problemId={task.id}
          starterCode={starterCode}
          questionText={task.question}
          hints={hints}
          onSubmit={handleCodeSubmit}
        />
      );
    }
    case "lab_exercise": {
      const { target_url, category, difficulty, hints } = readLabMeta(meta);
      if (!target_url) {
        return (
          <p role="alert" className="text-xs text-destructive">
            Lab target URL missing — cannot render this task yet.
          </p>
        );
      }
      return (
        <LabExerciseBlock
          problemId={task.id}
          questionText={task.question}
          targetUrl={target_url}
          category={category}
          difficulty={difficulty}
          hints={hints}
          onSubmit={handleLabSubmit}
        />
      );
    }
    case "mc":
    case "multiple_choice":
      return (
        <McTaskRenderer
          taskId={task.id}
          options={task.options ?? {}}
          onSubmit={handleDrillSubmit}
        />
      );
    case "flashcard":
    case "tf":
    case "short_answer":
      return (
        <TextTaskRenderer
          taskId={task.id}
          questionType={task.question_type}
          onSubmit={handleDrillSubmit}
        />
      );
    default:
      return (
        <p className="text-xs text-muted-foreground">
          Unsupported task type: {task.question_type}
        </p>
      );
  }
}

interface McTaskRendererProps {
  taskId: string;
  options: Record<string, string>;
  onSubmit: (answer: string) => Promise<AnswerResult>;
}

function McTaskRenderer({ taskId, options, onSubmit }: McTaskRendererProps) {
  const optionKeys = Object.keys(options).sort();
  const [selected, setSelected] = useState<string | null>(null);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async (key: string) => {
    if (result || submitting) return;
    setSelected(key);
    setSubmitting(true);
    setError(null);
    try {
      const res = await onSubmit(key);
      setResult(res);
    } catch (err) {
      setSelected(null);
      setError(err instanceof Error ? err.message : "Couldn't submit. Retry?");
    } finally {
      setSubmitting(false);
    }
  };

  const buttonClass = (key: string) => {
    if (!result) {
      return key === selected
        ? "border-primary bg-primary/10"
        : "border-border hover:border-primary/50";
    }
    if (key === result.correct_answer) {
      return "border-emerald-500 bg-emerald-500/10";
    }
    if (key === selected && !result.is_correct) {
      return "border-destructive bg-destructive/10";
    }
    return "border-border opacity-60";
  };

  return (
    <div className="space-y-2" data-testid={`mc-renderer-${taskId}`}>
      {optionKeys.map((key) => (
        <button
          key={key}
          type="button"
          disabled={!!result || submitting}
          onClick={() => void handleClick(key)}
          data-testid={`mc-option-${taskId}-${key}`}
          className={`w-full text-left rounded-lg border px-3 py-2 text-sm min-h-[44px] transition-colors disabled:cursor-default ${buttonClass(key)}`}
        >
          <span className="font-medium mr-2">{key.toUpperCase()}.</span>
          {options[key]}
        </button>
      ))}
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
      {result?.explanation && (
        <p className="text-xs text-muted-foreground mt-2">{result.explanation}</p>
      )}
    </div>
  );
}

interface TextTaskRendererProps {
  taskId: string;
  questionType: string;
  onSubmit: (answer: string) => Promise<AnswerResult>;
}

function TextTaskRenderer({
  taskId,
  questionType,
  onSubmit,
}: TextTaskRendererProps) {
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const placeholder =
    questionType === "tf"
      ? "true or false"
      : questionType === "flashcard"
        ? "Your recall"
        : "Your answer";

  const handleSubmit = async () => {
    if (result || submitting || !answer.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await onSubmit(answer);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't submit. Retry?");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-2" data-testid={`text-renderer-${taskId}`}>
      <input
        type="text"
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        placeholder={placeholder}
        disabled={!!result || submitting}
        data-testid={`text-input-${taskId}`}
        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm min-h-[44px]"
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            void handleSubmit();
          }
        }}
      />
      <button
        type="button"
        onClick={() => void handleSubmit()}
        disabled={!!result || submitting || !answer.trim()}
        data-testid={`text-submit-${taskId}`}
        className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
      >
        {submitting ? "…" : "Submit"}
      </button>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
      {result && (
        result.is_correct ? (
          <div
            data-testid={`text-result-${taskId}`}
            className="rounded-lg bg-emerald-500/10 px-3 py-2 text-xs text-emerald-800"
          >
            <p className="font-medium">
              Correct
              {result.explanation ? ` — ${result.explanation}` : ""}
            </p>
            <div className="mt-2">
              <ExplainStep problemId={taskId} correct={true} />
            </div>
          </div>
        ) : (
          <div data-testid={`text-result-${taskId}`}>
            <MissBanner
              problemId={taskId}
              revealedAnswer={result.correct_answer ?? null}
            >
              {result.explanation ? (
                <p className="text-xs text-muted-foreground whitespace-pre-wrap">
                  {result.explanation}
                </p>
              ) : null}
            </MissBanner>
          </div>
        )
      )}
    </div>
  );
}
