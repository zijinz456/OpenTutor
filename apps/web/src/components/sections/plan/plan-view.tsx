"use client";

import { useEffect, useState } from "react";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getExamPrepPlan,
  listStudyGoals,
  listStudyPlanBatches,
  saveStudyPlan,
  submitAgentTask,
  type StudyGoal,
} from "@/lib/api";
import { AiFeatureBlocked } from "@/components/shared/ai-feature-blocked";
import { useBatchManager } from "@/hooks/use-batch-manager";
import { toast } from "sonner";
import { updateUnlockContext } from "@/lib/block-system/feature-unlock";

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
        // Track hasDeadline for feature-unlock
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
        /* ignore */
      }
    })();
    return () => { cancelled = true; };
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
            {urgent && (
              <span className="shrink-0 rounded bg-destructive/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wider">
                urgent
              </span>
            )}
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
}

export function PlanView({
  courseId,
  aiActionsEnabled = true,
}: PlanViewProps) {
  const { saving, latestBatch, wrapSave } = useBatchManager({
    courseId,
    refreshSection: "plan",
    listFn: listStudyPlanBatches,
  });
  const [daysUntilExam, setDaysUntilExam] = useState("7");
  const [planMarkdown, setPlanMarkdown] = useState("");
  const [loading, setLoading] = useState(false);
  const [queueing, setQueueing] = useState(false);

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

  return (
    <div
      className="flex-1 flex flex-col overflow-hidden"
      data-testid="study-plan-panel"
    >
      <ExamCountdown courseId={courseId} />
      <div className="px-3 py-2 border-b flex items-center gap-2 text-xs text-muted-foreground">
        <span>Exam prep plan</span>
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
          <div
            className="prose prose-sm max-w-none"
            data-testid="study-plan-content"
          >
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
