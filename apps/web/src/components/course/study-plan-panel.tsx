"use client";

import { useCallback, useEffect, useState } from "react";
import { MarkdownRenderer } from "@/components/course/markdown-renderer";
import { CalendarDays, Download, Loader2, ShieldCheck, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getExamPrepPlan,
  listStudyPlanBatches,
  saveStudyPlan,
  submitAgentTask,
  type GeneratedAssetBatchSummary,
} from "@/lib/api";
import { toast } from "sonner";

interface StudyPlanPanelProps {
  courseId: string;
}

export function StudyPlanPanel({ courseId }: StudyPlanPanelProps) {
  const [daysUntilExam, setDaysUntilExam] = useState("7");
  const [planMarkdown, setPlanMarkdown] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const [batches, setBatches] = useState<GeneratedAssetBatchSummary[]>([]);

  const loadBatches = useCallback(async () => {
    try {
      setBatches(await listStudyPlanBatches(courseId));
    } catch {
      setBatches([]);
    }
  }, [courseId]);

  useEffect(() => {
    void loadBatches();
  }, [loadBatches]);

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
    setSaving(true);
    try {
      const result = await saveStudyPlan(courseId, planMarkdown, "Exam Prep Plan", replaceBatchId);
      toast.success(result.replaced ? `Replaced plan with version ${result.version}` : "Saved study plan");
      await loadBatches();
    } catch (error) {
      toast.error((error as Error).message || "Failed to save study plan");
    } finally {
      setSaving(false);
    }
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

  const latestBatch = batches.find((batch) => batch.is_active) ?? null;

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-testid="study-plan-panel">
      <div className="px-3 py-2 border-b flex items-center gap-2 text-xs text-muted-foreground">
        <CalendarDays className="h-4 w-4" />
        <span>Exam prep plan</span>
        <div className="ml-auto flex items-center gap-2">
          {planMarkdown && latestBatch?.is_active && (
            <Button size="sm" variant="outline" onClick={() => handleSave(latestBatch.batch_id)} disabled={saving || loading}>
              <Download className="h-4 w-4 mr-1" />
              Replace Latest
            </Button>
          )}
          {planMarkdown && (
            <Button size="sm" variant="outline" onClick={() => handleSave()} disabled={saving || loading}>
              <Download className="h-4 w-4 mr-1" />
              Save New
            </Button>
          )}
          <Input
            data-testid="study-plan-days-input"
            value={daysUntilExam}
            onChange={(e) => setDaysUntilExam(e.target.value)}
            className="h-8 w-20 text-xs"
            inputMode="numeric"
            placeholder="days"
          />
          <Button size="sm" variant="outline" onClick={handleQueue} disabled={queueing || loading}>
            {queueing ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <ShieldCheck className="h-4 w-4 mr-1" />}
            Queue
          </Button>
          <Button data-testid="study-plan-generate" size="sm" onClick={handleGenerate} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Sparkles className="h-4 w-4 mr-1" />}
            Generate
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {planMarkdown ? (
          <div className="prose prose-sm max-w-none" data-testid="study-plan-content">
            <MarkdownRenderer content={planMarkdown} />
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-center">
            <div>
              <p className="text-sm text-muted-foreground mb-3">Generate a focused exam prep plan for this course</p>
              <Button size="sm" variant="outline" onClick={handleGenerate} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Sparkles className="h-4 w-4 mr-1" />}
                Create Plan
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
