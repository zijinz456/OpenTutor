"use client";

import { useEffect, useMemo, useState } from "react";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getExamPrepPlan,
  getReviewSession,
  listStudyGoals,
  listStudyPlanBatches,
  saveStudyPlan,
  submitAgentTask,
  type ReviewItem,
  type StudyGoal,
} from "@/lib/api";
import { AiFeatureBlocked } from "@/components/shared/ai-feature-blocked";
import { useBatchManager } from "@/hooks/use-batch-manager";
import { toast } from "sonner";
import { updateUnlockContext } from "@/lib/block-system/feature-unlock";
import type { LearningMode } from "@/lib/block-system/types";

// ── Helpers ──

const MODE_TITLE: Record<LearningMode, string> = {
  course_following: "Course Following Plan",
  self_paced: "Self-Paced Learning Path",
  exam_prep: "Exam Countdown Plan",
  maintenance: "Maintenance Review Queue",
};

const MODE_DESC: Record<LearningMode, string> = {
  course_following: "Track deadlines, readings, and assignments on a timeline.",
  self_paced: "Follow a concept-first path and close your weakest gaps daily.",
  exam_prep: "Generate a focused, day-by-day countdown plan for your exam.",
  maintenance: "Keep knowledge fresh by reviewing concepts that are fading.",
};

function formatDateLabel(raw: string | null): string {
  if (!raw) return "No date";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return "No date";
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function getDaysLeft(raw: string | null): number | null {
  if (!raw) return null;
  const target = new Date(raw).getTime();
  if (Number.isNaN(target)) return null;
  return Math.ceil((target - Date.now()) / 86_400_000);
}

// ── Exam Countdown Banner ──

interface UpcomingDeadline extends StudyGoal {
  daysLeft: number;
}

function ExamCountdown({ courseId }: { courseId: string }) {
  const [upcoming, setUpcoming] = useState<UpcomingDeadline[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const goals = await listStudyGoals(courseId, "active");
        if (cancelled) return;
        const now = Date.now();

        if (goals.some((g) => g.target_date)) {
          updateUnlockContext(courseId, { hasDeadline: true });
        }

        const computed = goals
          .filter((g) => g.target_date)
          .map((g) => {
            const target = new Date(g.target_date!).getTime();
            const daysLeft = Math.ceil((target - now) / 86_400_000);
            return { ...g, daysLeft };
          })
          .filter((g) => g.daysLeft >= 0 && g.daysLeft <= 30)
          .sort((a, b) => a.daysLeft - b.daysLeft);
        setUpcoming(computed);
      } catch {
        // ignore
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  if (upcoming.length === 0) return null;

  return (
    <div className="border-b bg-amber-50 dark:bg-amber-950/30 px-3 py-2 space-y-1">
      {upcoming.map((g) => {
        const urgent = g.daysLeft <= 3;
        return (
          <div
            key={g.id}
            className={`flex items-center gap-2 text-xs ${urgent ? "font-semibold text-destructive" : "text-amber-800 dark:text-amber-200"}`}
          >
            <span className="tabular-nums">
              {g.daysLeft === 0 ? "TODAY" : g.daysLeft === 1 ? "1 day" : `${g.daysLeft} days`}
            </span>
            <span className="truncate flex-1">{g.title}</span>
            {urgent ? (
              <span className="shrink-0 rounded bg-destructive/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wider">
                urgent
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

// ── Mode Views ──

function CourseFollowingTimeline({ goals }: { goals: StudyGoal[] }) {
  const timeline = goals
    .filter((g) => g.target_date)
    .sort((a, b) => new Date(a.target_date!).getTime() - new Date(b.target_date!).getTime());

  if (timeline.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No dated goals yet. Add your first deadline to start a syllabus timeline.
      </p>
    );
  }

  return (
    <div className="space-y-2.5">
      {timeline.map((goal) => {
        const daysLeft = getDaysLeft(goal.target_date);
        const urgencyClass =
          daysLeft == null
            ? "text-muted-foreground"
            : daysLeft < 0
              ? "text-destructive"
              : daysLeft <= 3
                ? "text-warning"
                : "text-muted-foreground";
        return (
          <div key={goal.id} className="rounded-lg border border-border p-3">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">{goal.title}</p>
                {goal.next_action ? (
                  <p className="text-xs text-muted-foreground mt-1">Next: {goal.next_action}</p>
                ) : null}
              </div>
              <div className="text-right shrink-0">
                <p className="text-xs text-foreground">{formatDateLabel(goal.target_date)}</p>
                <p className={`text-[11px] mt-0.5 ${urgencyClass}`}>
                  {daysLeft == null
                    ? "No deadline"
                    : daysLeft < 0
                      ? "Overdue"
                      : daysLeft === 0
                        ? "Today"
                        : `${daysLeft}d left`}
                </p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function SelfPacedPath({ goals, reviewItems }: { goals: StudyGoal[]; reviewItems: ReviewItem[] }) {
  const activeGoals = goals.filter((g) => g.status !== "completed");
  const weakConcepts = [...reviewItems]
    .sort((a, b) => a.mastery - b.mastery)
    .slice(0, 8);

  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
          Checklist
        </h4>
        {activeGoals.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No active learning goals yet. Add goals to build a guided concept path.
          </p>
        ) : (
          <div className="space-y-2">
            {activeGoals.map((goal) => (
              <div key={goal.id} className="rounded-lg border border-border p-3">
                <p className="text-sm font-medium text-foreground">{goal.title}</p>
                <p className="text-xs text-muted-foreground mt-1">{goal.objective || "No objective provided"}</p>
                {goal.next_action ? (
                  <p className="text-xs text-brand mt-1">Next action: {goal.next_action}</p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
          Suggested next concepts
        </h4>
        {weakConcepts.length === 0 ? (
          <p className="text-sm text-muted-foreground">Practice more to generate concept-level recommendations.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {weakConcepts.map((item) => (
              <div key={item.concept_id} className="rounded-lg border border-border p-2.5">
                <p className="text-sm font-medium truncate">{item.concept_label}</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Mastery {Math.round(item.mastery * 100)}% · Stability {item.stability_days}d
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MaintenanceQueue({ reviewItems }: { reviewItems: ReviewItem[] }) {
  const rank = { overdue: 0, urgent: 1, warning: 2 } as const;
  const dueItems = reviewItems
    .filter((i) => i.urgency === "overdue" || i.urgency === "urgent" || i.urgency === "warning")
    .sort((a, b) => {
      const ra = rank[a.urgency as keyof typeof rank] ?? 99;
      const rb = rank[b.urgency as keyof typeof rank] ?? 99;
      if (ra !== rb) return ra - rb;
      return a.retrievability - b.retrievability;
    });

  if (dueItems.length === 0) {
    return <p className="text-sm text-muted-foreground">No concepts are fading right now. Great retention.</p>;
  }

  return (
    <div className="space-y-2.5">
      {dueItems.map((item) => {
        const urgencyStyle =
          item.urgency === "overdue"
            ? "text-destructive"
            : item.urgency === "urgent"
              ? "text-warning"
              : "text-muted-foreground";

        return (
          <div key={`${item.concept_id}-${item.urgency}`} className="rounded-lg border border-border p-3">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground truncate">{item.concept_label}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Retrievability {Math.round(item.retrievability * 100)}% · Stability {item.stability_days}d
                </p>
              </div>
              <span className={`text-xs font-medium uppercase ${urgencyStyle}`}>{item.urgency}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── PlanView ──

interface PlanViewProps {
  courseId: string;
  aiActionsEnabled?: boolean;
  learningMode?: LearningMode;
}

export function PlanView({
  courseId,
  aiActionsEnabled = true,
  learningMode,
}: PlanViewProps) {
  const mode: LearningMode = learningMode ?? "course_following";

  const { saving, latestBatch, wrapSave } = useBatchManager({
    courseId,
    refreshSection: "plan",
    listFn: listStudyPlanBatches,
  });
  const [daysUntilExam, setDaysUntilExam] = useState("7");
  const [planMarkdown, setPlanMarkdown] = useState("");
  const [loading, setLoading] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const [goals, setGoals] = useState<StudyGoal[]>([]);
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [loadingContext, setLoadingContext] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoadingContext(true);

    Promise.all([
      listStudyGoals(courseId).catch(() => [] as StudyGoal[]),
      getReviewSession(courseId, 30).then((r) => r.items).catch(() => [] as ReviewItem[]),
    ])
      .then(([nextGoals, nextReviewItems]) => {
        if (cancelled) return;
        setGoals(nextGoals);
        setReviewItems(nextReviewItems);
        if (nextGoals.some((g) => g.target_date)) {
          updateUnlockContext(courseId, { hasDeadline: true });
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingContext(false);
      });

    return () => {
      cancelled = true;
    };
  }, [courseId]);

  const modeLabel = useMemo(() => MODE_TITLE[mode], [mode]);
  const modeDesc = useMemo(() => MODE_DESC[mode], [mode]);

  const handleGenerate = async () => {
    setLoading(true);
    try {
      const days = Math.max(1, Number.parseInt(daysUntilExam || "7", 10) || 7);
      const result = await getExamPrepPlan(courseId, days);
      setPlanMarkdown(result.plan);
      toast.success(`Generated ${days}-day prep plan`);
    } catch (error) {
      toast.error((error as Error).message || "Failed to generate study plan");
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (replaceBatchId?: string) => {
    if (!planMarkdown.trim()) return;
    await wrapSave(() =>
      saveStudyPlan(courseId, planMarkdown, "Exam Prep Plan", replaceBatchId),
    );
  };

  const handleQueue = async () => {
    setQueueing(true);
    try {
      const days = Math.max(1, Number.parseInt(daysUntilExam || "7", 10) || 7);
      await submitAgentTask({
        task_type: "exam_prep",
        title: "Queued exam prep plan",
        course_id: courseId,
        summary: `Generate a ${days}-day exam prep plan in the background.`,
        input_json: { course_id: courseId, days_until_exam: days },
        source: "study_plan_panel",
        requires_approval: true,
        max_attempts: 2,
      });
      toast.success("Queued exam prep task for approval in Activity");
    } catch (error) {
      toast.error((error as Error).message || "Failed to queue exam prep task");
    } finally {
      setQueueing(false);
    }
  };

  if (mode === "exam_prep") {
    return (
      <div className="flex-1 flex flex-col overflow-hidden" data-testid="study-plan-panel">
        <ExamCountdown courseId={courseId} />
        <div className="px-3 py-2 border-b flex items-center gap-2 text-xs text-muted-foreground">
          <div>
            <p className="text-foreground font-medium">{modeLabel}</p>
            <p>{modeDesc}</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {planMarkdown && latestBatch?.is_active ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => void handleSave(latestBatch.batch_id)}
                disabled={saving || loading}
              >
                Replace Latest
              </Button>
            ) : null}
            {planMarkdown ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => void handleSave()}
                disabled={saving || loading}
              >
                Save New
              </Button>
            ) : null}
            <Input
              data-testid="study-plan-days-input"
              value={daysUntilExam}
              onChange={(e) => setDaysUntilExam(e.target.value)}
              className="h-8 w-20 text-xs"
              inputMode="numeric"
              placeholder="days"
              disabled={!aiActionsEnabled || loading || queueing}
            />
            <Button
              size="sm"
              variant="outline"
              onClick={handleQueue}
              disabled={!aiActionsEnabled || queueing || loading}
            >
              {queueing ? <span className="mr-1 animate-pulse">...</span> : null}
              Queue
            </Button>
            <Button
              data-testid="study-plan-generate"
              size="sm"
              onClick={handleGenerate}
              disabled={!aiActionsEnabled || loading}
            >
              {loading ? <span className="mr-1 animate-pulse">...</span> : null}
              Generate
            </Button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {!aiActionsEnabled ? <AiFeatureBlocked compact className="mb-4" /> : null}
          {planMarkdown ? (
            <div className="prose prose-sm max-w-none" data-testid="study-plan-content">
              <MarkdownRenderer content={planMarkdown} />
            </div>
          ) : (
            <div className="h-full flex items-center justify-center text-center">
              <div>
                <p className="text-sm text-muted-foreground mb-3">
                  Generate a focused exam prep plan for this course
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleGenerate}
                  disabled={!aiActionsEnabled || loading}
                >
                  {loading ? <span className="mr-1 animate-pulse">...</span> : null}
                  Create Plan
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-testid="study-plan-panel">
      <div className="px-3 py-2 border-b">
        <p className="text-sm font-medium text-foreground">{modeLabel}</p>
        <p className="text-xs text-muted-foreground mt-0.5">{modeDesc}</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loadingContext ? (
          <div className="space-y-2">
            <div className="h-8 rounded bg-muted animate-pulse" />
            <div className="h-8 rounded bg-muted animate-pulse" />
            <div className="h-8 rounded bg-muted animate-pulse" />
          </div>
        ) : null}

        {!loadingContext && mode === "course_following" ? (
          <CourseFollowingTimeline goals={goals} />
        ) : null}
        {!loadingContext && mode === "self_paced" ? (
          <SelfPacedPath goals={goals} reviewItems={reviewItems} />
        ) : null}
        {!loadingContext && mode === "maintenance" ? (
          <MaintenanceQueue reviewItems={reviewItems} />
        ) : null}
      </div>
    </div>
  );
}
