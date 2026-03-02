"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getExamPrepPlan,
  listStudyPlanBatches,
  saveStudyPlan,
  type GeneratedAssetBatchSummary,
} from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";

interface PlanViewProps {
  courseId: string;
}

function extractMarkdown(batch: GeneratedAssetBatchSummary | null): string {
  const preview = batch?.preview as { markdown?: unknown } | undefined;
  return typeof preview?.markdown === "string" ? preview.markdown : "";
}

function formatDate(value: string | null | undefined) {
  if (!value) return "Unknown";
  return new Date(value).toLocaleString();
}

export function PlanView({ courseId }: PlanViewProps) {
  const t = useT();
  const [batches, setBatches] = useState<GeneratedAssetBatchSummary[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [draftPlan, setDraftPlan] = useState("");
  const [examTopic, setExamTopic] = useState("");
  const [daysUntilExam, setDaysUntilExam] = useState("7");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await listStudyPlanBatches(courseId);
        if (cancelled) return;
        setBatches(data);
        setSelectedBatchId((current) => current ?? data[0]?.batch_id ?? null);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load study plans");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  const selectedBatch = useMemo(
    () => batches.find((batch) => batch.batch_id === selectedBatchId) ?? batches[0] ?? null,
    [batches, selectedBatchId],
  );

  const displayedPlan = draftPlan.trim() || extractMarkdown(selectedBatch);

  const refreshBatches = async () => {
    const data = await listStudyPlanBatches(courseId);
    setBatches(data);
    setSelectedBatchId(data[0]?.batch_id ?? null);
  };

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    setSaveMessage(null);
    try {
      const days = Math.max(1, Number.parseInt(daysUntilExam, 10) || 7);
      const result = await getExamPrepPlan(courseId, days, examTopic.trim() || undefined);
      setDraftPlan(result.plan);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate plan");
    } finally {
      setGenerating(false);
    }
  };

  const handleSave = async () => {
    if (!draftPlan.trim()) return;
    setSaving(true);
    setError(null);
    setSaveMessage(null);
    try {
      await saveStudyPlan(
        courseId,
        draftPlan,
        examTopic.trim() || `${t("course.plan")} ${new Date().toLocaleDateString()}`,
        selectedBatch?.batch_id,
      );
      setDraftPlan("");
      setSaveMessage("Study plan saved.");
      await refreshBatches();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save study plan");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="h-4 w-36 rounded bg-muted animate-pulse" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <div className="grid gap-4 xl:grid-cols-[280px,1fr]">
        <aside className="space-y-4">
          <section className="rounded-xl border border-border bg-card p-4 space-y-3">
            <div>
              <h3 className="text-sm font-medium">{t("course.plan")}</h3>
              <p className="text-xs text-muted-foreground mt-1">
                Generate an exam prep draft, then save it as the current study plan.
              </p>
            </div>

            <label className="block space-y-1.5">
              <span className="text-xs text-muted-foreground">Exam topic</span>
              <Input
                value={examTopic}
                onChange={(e) => setExamTopic(e.target.value)}
                placeholder="Final exam, midterm, essay topic..."
              />
            </label>

            <label className="block space-y-1.5">
              <span className="text-xs text-muted-foreground">Days until exam</span>
              <Input
                type="number"
                min="1"
                max="365"
                value={daysUntilExam}
                onChange={(e) => setDaysUntilExam(e.target.value)}
              />
            </label>

            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                onClick={() => void handleGenerate()}
                disabled={generating}
              >
                {generating ? "Generating..." : "Generate Draft"}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => void handleSave()}
                disabled={saving || !draftPlan.trim()}
              >
                {saving ? "Saving..." : "Save Draft"}
              </Button>
            </div>
          </section>

          <section className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center justify-between gap-2 mb-3">
              <h3 className="text-sm font-medium">Saved Plans</h3>
              <Badge variant="outline">{batches.length}</Badge>
            </div>

            {batches.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No saved study plans yet.
              </p>
            ) : (
              <div className="space-y-2">
                {batches.map((batch) => {
                  const active = batch.batch_id === selectedBatch?.batch_id;
                  return (
                    <button
                      key={batch.batch_id}
                      type="button"
                      onClick={() => setSelectedBatchId(batch.batch_id)}
                      className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
                        active
                          ? "border-primary bg-primary/5"
                          : "border-border hover:border-primary/40"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-medium">
                          {batch.title || `Plan ${batch.batch_id.slice(0, 8)}`}
                        </span>
                        {batch.is_active && <Badge variant="secondary">Active</Badge>}
                      </div>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        Updated {formatDate(batch.updated_at)}
                      </p>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        </aside>

        <section className="rounded-xl border border-border bg-card min-h-[420px]">
          <div className="border-b border-border px-4 py-3 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-medium">
                {draftPlan.trim()
                  ? "Unsaved Draft"
                  : selectedBatch?.title || t("course.plan")}
              </h3>
              <p className="text-xs text-muted-foreground mt-1">
                {draftPlan.trim()
                  ? "Review the generated draft before saving it."
                  : selectedBatch
                    ? `Saved ${formatDate(selectedBatch.updated_at)}`
                    : "Generate or save a study plan to see it here."}
              </p>
            </div>
            {saveMessage && <Badge variant="secondary">{saveMessage}</Badge>}
          </div>

          {draftPlan.trim() ? (
            <div className="p-4 space-y-3">
              <Textarea
                value={draftPlan}
                onChange={(e) => setDraftPlan(e.target.value)}
                className="min-h-[340px] text-sm leading-6"
              />
            </div>
          ) : displayedPlan ? (
            <div className="p-4">
              <div className="whitespace-pre-wrap text-sm leading-6 text-foreground">
                {displayedPlan}
              </div>
            </div>
          ) : (
            <div className="flex h-full min-h-[340px] items-center justify-center p-8 text-center">
              <div>
                <h4 className="text-sm font-medium mb-1">{t("course.plan")}</h4>
                <p className="text-xs text-muted-foreground max-w-sm">
                  Generate a draft on the left or save one from agent output to keep it here.
                </p>
              </div>
            </div>
          )}

          {error && (
            <div className="border-t border-border px-4 py-3 text-xs text-destructive">
              {error}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
