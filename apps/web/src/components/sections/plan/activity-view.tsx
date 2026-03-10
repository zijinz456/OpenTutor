"use client";

import { useCallback, useEffect, useState } from "react";
import { useT, useTF } from "@/lib/i18n-context";
import {
  listAgentTasks,
  approveAgentTask,
  rejectAgentTask,
  markTaskNotificationsRead,
  listStudyGoals,
  type AgentTask,
  type AgentTaskReview,
  type AgentTaskStepResult,
  type StudyGoal,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useChatStore } from "@/store/chat";

interface ActivityViewProps {
  courseId: string;
}

const STATUS_COLORS: Record<string, string> = {
  pending_approval: "bg-zinc-200 text-zinc-800 dark:bg-zinc-700/50 dark:text-zinc-300",
  running: "bg-zinc-100 text-zinc-800 dark:bg-zinc-800/50 dark:text-zinc-300",
  completed: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800/50 dark:text-zinc-400",
  failed: "bg-zinc-200 text-zinc-800 dark:bg-zinc-700/50 dark:text-zinc-300",
  queued: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  cancelled: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  rejected: "bg-zinc-200 text-zinc-700 dark:bg-zinc-700/50 dark:text-zinc-300",
};

function statusColor(status: string) {
  return STATUS_COLORS[status] ?? "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300";
}

function statusLabel(status: string, t: (key: string) => string): string {
  const key = `activity.status.${status}`;
  const translated = t(key);
  if (translated !== key) return translated;
  return status.replaceAll("_", " ");
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function getTaskReview(task: AgentTask): AgentTaskReview | null {
  const result = asRecord(task.result_json);
  const review = asRecord(result?.task_review);
  if (!review) return null;
  return review as unknown as AgentTaskReview;
}

function getTaskSteps(task: AgentTask): AgentTaskStepResult[] {
  if (Array.isArray(task.step_results) && task.step_results.length > 0) {
    return task.step_results as AgentTaskStepResult[];
  }
  const result = asRecord(task.result_json);
  const steps = result?.steps;
  return Array.isArray(steps) ? (steps as AgentTaskStepResult[]) : [];
}

function formatPercent(value: unknown): string | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  return `${Math.round(value * 100)}%`;
}

function getFailureSteps(task: AgentTask): AgentTaskStepResult[] {
  return getTaskSteps(task).filter((step) => step.success === false);
}

function getVerifierSummary(step: AgentTaskStepResult): string | null {
  const verifier = asRecord(step.verifier);
  const code = typeof verifier?.code === "string" ? verifier.code : null;
  const message = typeof verifier?.message === "string" ? verifier.message : null;
  if (code && message) return `${code}: ${message}`;
  return code ?? message;
}

function isGuidedSessionPaused(task: AgentTask): boolean {
  const checkpoint = asRecord(task.checkpoint_json);
  if (checkpoint?.phase && task.status !== "completed" && task.status !== "failed") {
    return true;
  }
  return task.status === "cancelled" || task.status === "rejected";
}

function GuidedSessionButton({ task, courseId, t }: { task: AgentTask; courseId: string; t: (key: string) => string }) {
  if (task.task_type !== "guided_session") return null;

  const paused = isGuidedSessionPaused(task);
  const label = paused ? t("guidedSession.resume") : t("guidedSession.start");
  const trigger = paused
    ? `[GUIDED_SESSION:resume:${task.id}]`
    : `[GUIDED_SESSION:start:${task.id}]`;

  const handleClick = () => {
    const chatStore = useChatStore.getState();
    chatStore.sendMessage(courseId, trigger);
  };

  return (
    <div className="mt-2">
      <p className="text-[10px] text-muted-foreground mb-1.5">{t("guidedSession.description")}</p>
      <button
        type="button"
        onClick={handleClick}
        className="px-4 py-2 rounded-xl bg-brand text-brand-foreground text-sm font-medium hover:opacity-90 transition-opacity"
      >
        {label}
      </button>
    </div>
  );
}

export function ActivityView({ courseId }: ActivityViewProps) {
  const t = useT();
  const tf = useTF();

  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [goals, setGoals] = useState<StudyGoal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<Set<string>>(new Set());

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [tasksResult, goalsResult] = await Promise.all([
        listAgentTasks(courseId),
        listStudyGoals(courseId),
      ]);
      setTasks(tasksResult);
      setGoals(goalsResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("activity.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [courseId, t]);

  useEffect(() => {
    fetchData();
    // Poll every 15 seconds for task status updates
    const interval = setInterval(fetchData, 15_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const act = async (taskId: string, fn: (id: string) => Promise<AgentTask>) => {
    setActing((s) => new Set(s).add(taskId));
    try {
      const updated = await fn(taskId);
      await markTaskNotificationsRead(taskId).catch(() => undefined);
      setTasks((prev) => prev.map((tk) => (tk.id === taskId ? updated : tk)));
    } catch { /* keep current state */ } finally {
      setActing((s) => { const n = new Set(s); n.delete(taskId); return n; });
    }
  };

  if (loading) return (
    <div className="flex-1 flex items-center justify-center p-8">
      <p className="text-xs text-muted-foreground animate-pulse">{t("activity.loading")}</p>
    </div>
  );
  if (error) return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 gap-2">
      <p className="text-xs text-destructive">{error}</p>
      <Button variant="outline" size="sm" onClick={fetchData}>{t("activity.retry")}</Button>
    </div>
  );
  if (tasks.length === 0 && goals.length === 0) return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
      <h3 className="text-sm font-medium mb-1">{t("course.activity")}</h3>
      <p className="text-xs text-muted-foreground max-w-xs">
        {t("activity.empty")}
      </p>
    </div>
  );

  /* ---------- Group tasks ---------- */

  const pending = tasks.filter((tk) => tk.status === "pending_approval");
  const others = tasks.filter((tk) => tk.status !== "pending_approval");

  const grouped: Record<string, AgentTask[]> = {};
  for (const tk of others) {
    (grouped[tk.status] ??= []).push(tk);
  }
  const statusOrder = ["running", "queued", "completed", "failed", "cancelled", "rejected"];
  const sortedStatuses = Object.keys(grouped).sort(
    (a, b) => (statusOrder.indexOf(a) === -1 ? 99 : statusOrder.indexOf(a)) -
              (statusOrder.indexOf(b) === -1 ? 99 : statusOrder.indexOf(b)),
  );

  /* ---------- Render ---------- */

  return (
    <div role="region" aria-label="Agent activity" className="flex-1 flex flex-col gap-4 p-4 overflow-y-auto scrollbar-thin">
      {/* Pending approval */}
      {pending.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-600 dark:text-zinc-400 mb-2">
            {tf("activity.needsApproval", { count: pending.length })}
          </h3>
          <div className="flex flex-col gap-2">
            {pending.map((tk) => (
              <div key={tk.id} className="rounded-2xl card-shadow bg-card p-3.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{tk.title}</p>
                    {tk.summary && <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{tk.summary}</p>}
                    <p className="text-[10px] text-muted-foreground mt-1">{tk.task_type} &middot; {tk.source}</p>
                    <GuidedSessionButton task={tk} courseId={courseId} t={t} />
                  </div>
                  <div className="flex gap-1.5 shrink-0">
                    <Button size="sm" disabled={acting.has(tk.id)} onClick={() => act(tk.id, approveAgentTask)}>{t("activity.approve")}</Button>
                    <Button size="sm" variant="outline" disabled={acting.has(tk.id)} onClick={() => act(tk.id, rejectAgentTask)}>{t("activity.reject")}</Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Other tasks by status */}
      {sortedStatuses.map((status) => (
        <section key={status}>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-1.5">
            <Badge variant="outline" className={statusColor(status)}>{statusLabel(status, t)}</Badge>
            <span>({grouped[status].length})</span>
          </h3>
          <div className="flex flex-col gap-1.5">
            {grouped[status].map((tk) => (
              <div key={tk.id} className="rounded-xl bg-muted/30 p-3.5 text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-medium truncate flex-1">{tk.title}</span>
                  <Badge variant="outline" className={statusColor(tk.status)}>{statusLabel(tk.status, t)}</Badge>
                </div>
                {tk.summary && <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{tk.summary}</p>}
                <p className="text-[10px] text-muted-foreground mt-1">{tk.task_type} &middot; {tk.source}</p>
                <GuidedSessionButton task={tk} courseId={courseId} t={t} />
                {(() => {
                  const review = getTaskReview(tk);
                  const failedSteps = getFailureSteps(tk);
                  const showDiagnostics = review || failedSteps.length > 0;
                  if (!showDiagnostics) return null;

                  return (
                    <div className="mt-2 space-y-2 rounded-xl bg-muted/30 p-2.5">
                      {review?.outcome && (
                        <p className="text-[11px] text-foreground/90">{review.outcome}</p>
                      )}
                      {review?.blockers?.length ? (
                        <div className="space-y-1">
                          {review.blockers.slice(0, 3).map((blocker) => (
                            <p key={blocker} className="text-[11px] text-muted-foreground">
                              {t("activity.blocker")}: {blocker}
                            </p>
                          ))}
                        </div>
                      ) : null}
                      {review?.follow_up?.auto_queued ? (
                        <p className="text-[11px] text-muted-foreground">
                          {t("activity.repairQueued")}{review.follow_up.queued_task_id ? ` (${review.follow_up.queued_task_id.slice(0, 8)})` : ""}.
                        </p>
                      ) : null}
                      {failedSteps.slice(0, 2).map((step, idx) => {
                        const diagnostics = asRecord(step.verifier_diagnostics);
                        const requestCoverage = formatPercent(diagnostics?.request_coverage);
                        const evidenceCoverage = formatPercent(diagnostics?.evidence_coverage);
                        const requestTerms = Array.isArray(diagnostics?.request_overlap_terms)
                          ? diagnostics.request_overlap_terms.filter((item): item is string => typeof item === "string").slice(0, 4)
                          : [];
                        const evidenceTerms = Array.isArray(diagnostics?.evidence_overlap_terms)
                          ? diagnostics.evidence_overlap_terms.filter((item): item is string => typeof item === "string").slice(0, 4)
                          : [];
                        const verifierSummary = getVerifierSummary(step);

                        return (
                          <div key={`${tk.id}-${step.step_index ?? idx}`} className="rounded-xl border border-border/60 bg-background/70 p-2.5">
                            <p className="text-[11px] font-medium">
                              {step.title ?? step.step_type ?? tf("activity.step", { index: idx + 1 })}
                            </p>
                            {step.error ? <p className="text-[11px] text-muted-foreground mt-0.5">{step.error}</p> : null}
                            {verifierSummary ? <p className="text-[11px] text-muted-foreground mt-0.5">{t("activity.verifier")}: {verifierSummary}</p> : null}
                            {(requestCoverage || evidenceCoverage) ? (
                              <div className="mt-1 flex flex-wrap gap-1.5">
                                {requestCoverage ? <Badge variant="outline" className="text-[10px]">{t("activity.request")} {requestCoverage}</Badge> : null}
                                {evidenceCoverage ? <Badge variant="outline" className="text-[10px]">{t("activity.evidence")} {evidenceCoverage}</Badge> : null}
                              </div>
                            ) : null}
                            {requestTerms.length > 0 ? (
                              <p className="text-[10px] text-muted-foreground mt-1">{t("activity.coveredRequestTerms")}: {requestTerms.join(", ")}</p>
                            ) : null}
                            {evidenceTerms.length > 0 ? (
                              <p className="text-[10px] text-muted-foreground">{t("activity.usedEvidence")}: {evidenceTerms.join(", ")}</p>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}
              </div>
            ))}
          </div>
        </section>
      ))}

      {/* Goals */}
      {goals.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            {tf("activity.goals", { count: goals.length })}
          </h3>
          <div className="flex flex-col gap-1.5">
            {goals.map((g) => (
              <div key={g.id} className="rounded-xl bg-muted/30 p-3.5">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium truncate flex-1">{g.title}</span>
                  <Badge variant="secondary" className="text-[10px]">{statusLabel(g.status, t)}</Badge>
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">{g.objective}</p>
                {g.current_milestone && <p className="text-[10px] text-muted-foreground mt-1">{t("activity.milestone")}: {g.current_milestone}</p>}
                {g.next_action && <p className="text-[10px] text-muted-foreground">{t("activity.next")}: {g.next_action}</p>}
                {g.target_date && <p className="text-[10px] text-muted-foreground">{t("activity.target")}: {g.target_date}</p>}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
