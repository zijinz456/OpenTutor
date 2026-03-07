"use client";

import { useEffect, useMemo, useState } from "react";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getExamPrepPlan,
  getReviewSession,
  getStudyPlans,
  listStudyGoals,
  listStudyPlanBatches,
  saveStudyPlan,
  submitAgentTask,
  type ReviewItem,
  type StudyGoal,
  type StudyPlanResponse,
} from "@/lib/api";
import { AiFeatureBlocked } from "@/components/shared/ai-feature-blocked";
import { useBatchManager } from "@/hooks/use-batch-manager";
import { toast } from "sonner";
import { updateUnlockContext } from "@/lib/block-system/feature-unlock";
import type { LearningMode } from "@/lib/block-system/types";
import { useT, useTF } from "@/lib/i18n-context";

// ── Helpers ──

function formatDateLabel(raw: string | null, fallback: string): string {
  if (!raw) return fallback;
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return fallback;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

type TranslateFn = (key: string) => string;
type TranslateFormatFn = (key: string, vars?: Record<string, string | number | null | undefined>) => string;

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

function ExamCountdown({
  courseId,
  t,
  tf,
}: {
  courseId: string;
  t: TranslateFn;
  tf: TranslateFormatFn;
}) {
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
    <div className="border-b border-border/60 bg-amber-50 dark:bg-amber-950/30 px-3 py-2 space-y-1">
      {upcoming.map((g) => {
        const urgent = g.daysLeft <= 3;
        return (
          <div
            key={g.id}
            className={`flex items-center gap-2 text-xs ${urgent ? "font-semibold text-destructive" : "text-amber-800 dark:text-amber-200"}`}
          >
            <span className="tabular-nums">
              {g.daysLeft === 0
                ? t("plan.banner.today")
                : g.daysLeft === 1
                  ? t("plan.banner.oneDay")
                  : tf("plan.banner.manyDays", { days: g.daysLeft })}
            </span>
            <span className="truncate flex-1">{g.title}</span>
            {urgent ? (
              <span className="shrink-0 rounded bg-destructive/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wider">
                {t("plan.banner.urgent")}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

// ── Mode Views ──

function CourseFollowingTimeline({
  goals,
  t,
  tf,
}: {
  goals: StudyGoal[];
  t: TranslateFn;
  tf: TranslateFormatFn;
}) {
  const timeline = goals
    .filter((g) => g.target_date)
    .sort((a, b) => new Date(a.target_date!).getTime() - new Date(b.target_date!).getTime());

  if (timeline.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("plan.timeline.empty")}
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
          <div key={goal.id} className="rounded-2xl card-shadow p-3.5">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">{goal.title}</p>
                {goal.next_action ? (
                  <p className="text-xs text-muted-foreground mt-1">{t("plan.path.nextPrefix")} {goal.next_action}</p>
                ) : null}
              </div>
              <div className="text-right shrink-0">
                <p className="text-xs text-foreground">{formatDateLabel(goal.target_date, t("plan.deadline.noDate"))}</p>
                <p className={`text-[11px] mt-0.5 ${urgencyClass}`}>
                  {daysLeft == null
                    ? t("plan.deadline.none")
                    : daysLeft < 0
                      ? t("plan.deadline.overdue")
                      : daysLeft === 0
                        ? t("plan.deadline.today")
                        : tf("plan.deadline.daysLeft", { days: daysLeft })}
                </p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function SelfPacedPath({
  goals,
  reviewItems,
  t,
}: {
  goals: StudyGoal[];
  reviewItems: ReviewItem[];
  t: TranslateFn;
}) {
  const activeGoals = goals.filter((g) => g.status !== "completed");
  const weakConcepts = [...reviewItems]
    .sort((a, b) => a.mastery - b.mastery)
    .slice(0, 8);

  const nextUp = activeGoals.filter((g) => {
    if (!g.target_date) return !!g.next_action;
    const days = getDaysLeft(g.target_date);
    return days != null && days >= 0 && days <= 7;
  });
  const inProgress = activeGoals.filter((g) => !nextUp.some((n) => n.id === g.id));
  const completed = goals.filter((g) => g.status === "completed").slice(0, 6);

  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
          {t("plan.path.title")}
        </h4>
        {activeGoals.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("plan.path.empty")}
          </p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="rounded-2xl card-shadow p-3 space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("plan.path.nextUp")}</p>
              {nextUp.length === 0 ? (
                <p className="text-xs text-muted-foreground">{t("plan.path.nextUp.empty")}</p>
              ) : (
                nextUp.map((goal) => (
                  <div key={goal.id} className="rounded-xl bg-muted/30 p-2.5">
                    <p className="text-xs font-medium">{goal.title}</p>
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      {goal.target_date
                        ? formatDateLabel(goal.target_date, t("plan.deadline.noDate"))
                        : t("plan.deadline.noDate")}
                    </p>
                  </div>
                ))
              )}
            </div>
            <div className="rounded-2xl card-shadow p-3 space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("plan.path.inProgress")}</p>
              {inProgress.length === 0 ? (
                <p className="text-xs text-muted-foreground">{t("plan.path.inProgress.empty")}</p>
              ) : (
                inProgress.slice(0, 6).map((goal) => (
                  <div key={goal.id} className="rounded-xl bg-muted/30 p-2.5">
                    <p className="text-xs font-medium">{goal.title}</p>
                    {goal.next_action ? (
                      <p className="text-[11px] text-brand mt-0.5">{t("plan.path.nextPrefix")} {goal.next_action}</p>
                    ) : (
                      <p className="text-[11px] text-muted-foreground mt-0.5">{t("plan.path.noNextAction")}</p>
                    )}
                  </div>
                ))
              )}
            </div>
            <div className="rounded-2xl card-shadow p-3 space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("plan.path.done")}</p>
              {completed.length === 0 ? (
                <p className="text-xs text-muted-foreground">{t("plan.path.done.empty")}</p>
              ) : (
                completed.map((goal) => (
                  <div key={goal.id} className="rounded-xl bg-muted/30 p-2.5">
                    <p className="text-xs font-medium">{goal.title}</p>
                    <p className="text-[11px] text-muted-foreground mt-0.5">{t("plan.path.completed")}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
          {t("plan.path.suggestedConcepts")}
        </h4>
        {weakConcepts.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("plan.path.suggestedConcepts.empty")}</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {weakConcepts.map((item) => (
              <div key={item.concept_id} className="rounded-xl bg-muted/30 p-3.5">
                <p className="text-sm font-medium truncate">{item.concept_label}</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {t("plan.metric.mastery")} {Math.round(item.mastery * 100)}% · {t("plan.metric.stability")} {item.stability_days}d
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ExamCoverageChecklist({ reviewItems, t }: { reviewItems: ReviewItem[]; t: TranslateFn }) {
  const weakConcepts = [...reviewItems]
    .sort((a, b) => a.mastery - b.mastery)
    .slice(0, 8);
  if (weakConcepts.length === 0) {
    return (
      <div className="rounded-2xl card-shadow p-3.5">
        <p className="text-xs text-muted-foreground">{t("plan.exam.coverage.empty")}</p>
      </div>
    );
  }
  return (
    <div className="rounded-2xl card-shadow p-3.5 space-y-2.5">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("plan.exam.coverage")}</p>
      {weakConcepts.map((item) => (
        <div key={`${item.concept_id}-exam`} className="flex items-center gap-2">
          <div className="w-20 h-1.5 bg-muted rounded-full overflow-hidden shrink-0">
            <div className="h-full bg-warning rounded-full" style={{ width: `${Math.round(item.mastery * 100)}%` }} />
          </div>
          <p className="text-xs text-foreground truncate flex-1">{item.concept_label}</p>
          <span className="text-[11px] text-muted-foreground">{Math.round(item.mastery * 100)}%</span>
        </div>
      ))}
    </div>
  );
}

function MaintenanceQueue({ reviewItems, t }: { reviewItems: ReviewItem[]; t: TranslateFn }) {
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
    return <p className="text-sm text-muted-foreground">{t("plan.maintenance.empty")}</p>;
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
          <div key={`${item.concept_id}-${item.urgency}`} className="rounded-2xl card-shadow p-3.5">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground truncate">{item.concept_label}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {t("plan.metric.retrievability")} {Math.round(item.retrievability * 100)}% · {t("plan.metric.stability")} {item.stability_days}d
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

// ── Saved Plans ──

function SavedPlansList({
  plans,
  t,
  tf,
}: {
  plans: StudyPlanResponse[];
  t: TranslateFn;
  tf: TranslateFormatFn;
}) {
  if (plans.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">{t("plan.noPlans")}</p>
    );
  }

  return (
    <div className="space-y-2">
      {plans.map((plan) => (
        <div key={plan.id} className="rounded-2xl card-shadow p-3.5">
          <p className="text-sm font-medium text-foreground">{plan.name}</p>
          <p className="text-xs text-muted-foreground mt-1">
            {tf("plan.createdAt", {
              date: new Date(plan.created_at).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
                year: "numeric",
              }),
            })}
          </p>
        </div>
      ))}
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
  const t = useT();
  const tf = useTF();
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
  const [savedPlans, setSavedPlans] = useState<StudyPlanResponse[]>([]);
  const [loadingContext, setLoadingContext] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoadingContext(true);

    Promise.all([
      listStudyGoals(courseId).catch(() => [] as StudyGoal[]),
      getReviewSession(courseId, 30).then((r) => r.items).catch(() => [] as ReviewItem[]),
      getStudyPlans(courseId).catch(() => [] as StudyPlanResponse[]),
    ])
      .then(([nextGoals, nextReviewItems, nextPlans]) => {
        if (cancelled) return;
        setGoals(nextGoals);
        setReviewItems(nextReviewItems);
        setSavedPlans(nextPlans);
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

  const modeLabel = useMemo(() => t(`mode.${mode}`), [mode, t]);
  const modeDesc = useMemo(() => t(`mode.${mode}.desc`), [mode, t]);

  const handleGenerate = async () => {
    setLoading(true);
    try {
      const days = Math.max(1, Number.parseInt(daysUntilExam || "7", 10) || 7);
      const result = await getExamPrepPlan(courseId, days);
      setPlanMarkdown(result.plan);
      toast.success(tf("plan.exam.generated", { days }));
    } catch (error) {
      toast.error((error as Error).message || t("plan.exam.generateFailed"));
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (replaceBatchId?: string) => {
    if (!planMarkdown.trim()) return;
    await wrapSave(() =>
      saveStudyPlan(courseId, planMarkdown, t("plan.exam.saveTitle"), replaceBatchId),
    );
  };

  const handleQueue = async () => {
    setQueueing(true);
    try {
      const days = Math.max(1, Number.parseInt(daysUntilExam || "7", 10) || 7);
      await submitAgentTask({
        task_type: "exam_prep",
        title: t("plan.exam.taskTitle"),
        course_id: courseId,
        summary: tf("plan.exam.taskSummary", { days }),
        input_json: { course_id: courseId, days_until_exam: days },
        source: "study_plan_panel",
        requires_approval: true,
        max_attempts: 2,
      });
      toast.success(t("plan.exam.queued"));
    } catch (error) {
      toast.error((error as Error).message || t("plan.exam.queueFailed"));
    } finally {
      setQueueing(false);
    }
  };

  if (mode === "exam_prep") {
    return (
      <div className="flex-1 flex flex-col overflow-hidden" data-testid="study-plan-panel">
        <ExamCountdown courseId={courseId} t={t} tf={tf} />
        <div className="px-3 py-2 border-b border-border/60 flex items-center gap-2 text-xs text-muted-foreground">
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
                {t("plan.actions.replaceLatest")}
              </Button>
            ) : null}
            {planMarkdown ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => void handleSave()}
                disabled={saving || loading}
              >
                {t("plan.actions.saveNew")}
              </Button>
            ) : null}
            <Input
              data-testid="study-plan-days-input"
              value={daysUntilExam}
              onChange={(e) => setDaysUntilExam(e.target.value)}
              className="h-8 w-20 text-xs"
              inputMode="numeric"
              placeholder={t("plan.daysPlaceholder")}
              disabled={!aiActionsEnabled || loading || queueing}
            />
            <Button
              size="sm"
              variant="outline"
              onClick={handleQueue}
              disabled={!aiActionsEnabled || queueing || loading}
            >
              {queueing ? <span className="mr-1 animate-pulse">...</span> : null}
              {t("plan.actions.queue")}
            </Button>
            <Button
              data-testid="study-plan-generate"
              size="sm"
              onClick={handleGenerate}
              disabled={!aiActionsEnabled || loading}
            >
              {loading ? <span className="mr-1 animate-pulse">...</span> : null}
              {t("plan.actions.generate")}
            </Button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto scrollbar-thin p-4">
          {!aiActionsEnabled ? <AiFeatureBlocked compact className="mb-4" /> : null}
          {planMarkdown ? (
            <div className="space-y-4">
              <div className="prose prose-sm max-w-none" data-testid="study-plan-content">
                <MarkdownRenderer content={planMarkdown} />
              </div>
              <ExamCoverageChecklist reviewItems={reviewItems} t={t} />
            </div>
          ) : (
            <div className="space-y-4">
              <ExamCoverageChecklist reviewItems={reviewItems} t={t} />
              <div className="text-center pt-2">
                <p className="text-sm text-muted-foreground mb-3">
                  {t("plan.exam.emptyHint")}
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleGenerate}
                  disabled={!aiActionsEnabled || loading}
                >
                  {loading ? <span className="mr-1 animate-pulse">...</span> : null}
                  {t("plan.actions.createPlan")}
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
      <div className="px-3 py-2 border-b border-border/60">
        <p className="text-sm font-medium text-foreground">{modeLabel}</p>
        <p className="text-xs text-muted-foreground mt-0.5">{modeDesc}</p>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-4">
        {loadingContext ? (
          <div className="space-y-2">
            <div className="h-8 rounded bg-muted animate-pulse" />
            <div className="h-8 rounded bg-muted animate-pulse" />
            <div className="h-8 rounded bg-muted animate-pulse" />
          </div>
        ) : null}

        {!loadingContext && mode === "course_following" ? (
          <CourseFollowingTimeline goals={goals} t={t} tf={tf} />
        ) : null}
        {!loadingContext && mode === "self_paced" ? (
          <SelfPacedPath goals={goals} reviewItems={reviewItems} t={t} />
        ) : null}
        {!loadingContext && mode === "maintenance" ? (
          <MaintenanceQueue reviewItems={reviewItems} t={t} />
        ) : null}

        {!loadingContext && savedPlans.length > 0 ? (
          <div className="mt-4">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
              {t("plan.savedPlans")}
            </h4>
            <SavedPlansList plans={savedPlans} t={t} tf={tf} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
