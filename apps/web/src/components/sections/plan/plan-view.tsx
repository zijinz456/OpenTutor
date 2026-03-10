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

import { ExamCountdown } from "./_components/exam-countdown";
import { CourseFollowingTimeline } from "./_components/course-following-timeline";
import { SelfPacedPath } from "./_components/self-paced-path";
import { ExamCoverageChecklist } from "./_components/exam-coverage-checklist";
import { MaintenanceQueue } from "./_components/maintenance-queue";
import { SavedPlansList } from "./_components/saved-plans-list";

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
      <div role="region" aria-label="Study plan" className="flex-1 flex flex-col overflow-hidden" data-testid="study-plan-panel">
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
    <div role="region" aria-label="Study plan" className="flex-1 flex flex-col overflow-hidden" data-testid="study-plan-panel">
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
