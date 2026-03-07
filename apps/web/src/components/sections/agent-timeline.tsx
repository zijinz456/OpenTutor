"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { listAgendaRuns, type AgendaRun } from "@/lib/api";
import { useT } from "@/lib/i18n-context";

const SIGNAL_COLORS: Record<string, string> = {
  failed_task: "bg-destructive/20 text-destructive",
  deadline: "bg-warning/20 text-warning",
  active_goal: "bg-brand/20 text-brand",
  prerequisite_gap: "bg-warning/20 text-warning",
  forgetting_risk: "bg-info/20 text-info",
  weak_area: "bg-destructive/20 text-destructive",
  guided_session_ready: "bg-success/20 text-success",
  inactivity: "bg-muted text-muted-foreground",
  manual_override: "bg-brand/20 text-brand",
};

interface AgentTimelineProps {
  courseId: string;
}

type PriorityLevel = "high" | "medium" | "low";

function toTimestamp(value: string | null): number {
  if (!value) return 0;
  const ts = new Date(value).getTime();
  return Number.isNaN(ts) ? 0 : ts;
}

function getUrgencyScore(urgency: unknown): number {
  if (urgency === "overdue") return 4;
  if (urgency === "urgent") return 3;
  if (urgency === "warning") return 2;
  return 0;
}

function getPriority(run: AgendaRun): { level: PriorityLevel; score: number } {
  let score = 0;
  if (run.status === "failed") score += 4;
  if (run.status === "queued_task" || run.status === "resumed_task" || run.status === "retried_task") score += 1;

  const signals = Array.isArray(run.signals_json) ? run.signals_json : [];
  for (const signal of signals) {
    const urgency = (signal as Record<string, unknown>).urgency;
    score += getUrgencyScore(urgency);
  }

  if (run.top_signal_type === "failed_task" || run.top_signal_type === "weak_area") score += 2;
  if (run.top_signal_type === "manual_override") score += 1;

  if (score >= 6) return { level: "high", score };
  if (score >= 3) return { level: "medium", score };
  return { level: "low", score };
}

function resolveQuickPath(run: AgendaRun, courseId: string): string | null {
  const decision = run.decision_json;
  const decisionRecord = decision && typeof decision === "object"
    ? (decision as Record<string, unknown>)
    : null;
  const decisionAction = typeof decisionRecord?.action === "string"
    ? decisionRecord.action
    : "";

  if (decisionAction.includes("mode")) return `/course/${courseId}/profile`;
  if (run.top_signal_type === "deadline") return `/course/${courseId}/plan`;
  if (run.top_signal_type === "forgetting_risk") return `/course/${courseId}/review`;
  if (run.top_signal_type === "weak_area" || run.top_signal_type === "prerequisite_gap") {
    return `/course/${courseId}/practice?tab=quiz`;
  }
  if (run.top_signal_type === "active_goal") return `/course/${courseId}/plan`;
  if (run.top_signal_type === "failed_task") return `/course/${courseId}/profile?tab=agent`;
  return `/course/${courseId}/profile?tab=agent`;
}

export function AgentTimeline({ courseId }: AgentTimelineProps) {
  const router = useRouter();
  const t = useT();
  const [runsByCourse, setRunsByCourse] = useState<Record<string, AgendaRun[]>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listAgendaRuns(courseId, 20)
      .then((nextRuns) => {
        if (cancelled) return;
        setRunsByCourse((prev) => ({ ...prev, [courseId]: nextRuns }));
      })
      .catch(() => {
        if (cancelled) return;
        setRunsByCourse((prev) => ({ ...prev, [courseId]: [] }));
      });
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  const runs = runsByCourse[courseId];
  const loading = runs == null;

  const sortedRuns = useMemo(() => {
    if (!runs) return [];
    return [...runs].sort((a, b) => {
      const pa = getPriority(a);
      const pb = getPriority(b);
      if (pb.score !== pa.score) return pb.score - pa.score;
      return toTimestamp(b.created_at) - toTimestamp(a.created_at);
    });
  }, [runs]);

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <div className="h-4 w-32 bg-muted animate-pulse rounded" />
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="p-6 text-center">
        <p className="text-sm text-muted-foreground">
          {t("agent.timeline.empty")}
        </p>
      </div>
    );
  }

  const stats = {
    total: sortedRuns.length,
    completed: sortedRuns.filter((r) => r.status === "completed").length,
    signalTypes: new Set(sortedRuns.map((r) => r.top_signal_type).filter(Boolean)).size,
    needsAttention: sortedRuns.filter((r) => getPriority(r).level === "high").length,
  };

  return (
    <div className="space-y-4">
      {/* Stats summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 px-4">
        <div className="rounded-xl bg-muted/30 p-3.5 text-center">
          <p className="text-lg font-semibold">{stats.total}</p>
          <p className="text-[10px] text-muted-foreground">
            {t("agent.timeline.totalRuns")}
          </p>
        </div>
        <div className="rounded-xl bg-muted/30 p-3.5 text-center">
          <p className="text-lg font-semibold">{stats.completed}</p>
          <p className="text-[10px] text-muted-foreground">
            {t("agent.timeline.completed")}
          </p>
        </div>
        <div className="rounded-xl bg-muted/30 p-3.5 text-center">
          <p className="text-lg font-semibold">{stats.signalTypes}</p>
          <p className="text-[10px] text-muted-foreground">
            {t("agent.timeline.signalTypes")}
          </p>
        </div>
        <div className="rounded-xl bg-destructive/10 p-3.5 text-center">
          <p className="text-lg font-semibold text-destructive">{stats.needsAttention}</p>
          <p className="text-[10px] text-destructive/90">
            {t("agent.timeline.needsAttention")}
          </p>
        </div>
      </div>

      {/* Timeline */}
      <div className="relative px-4">
        <div className="absolute left-[27px] top-0 bottom-0 w-px bg-border/60" />
        <div className="space-y-3">
          {sortedRuns.map((run) => {
            const isExpanded = expandedId === run.id;
            const decision = run.decision_json;
            const decisionRecord = decision && typeof decision === "object"
              ? (decision as Record<string, unknown>)
              : null;
            const decisionTitle = typeof decisionRecord?.task_title === "string"
              ? decisionRecord.task_title
              : null;
            const decisionReason = typeof decisionRecord?.reason === "string"
              ? decisionRecord.reason
              : null;
            const decisionAction = typeof decisionRecord?.action === "string"
              ? decisionRecord.action
              : null;
            const priority = getPriority(run);
            const quickPath = resolveQuickPath(run, courseId);
            const signals = Array.isArray(run.signals_json) ? run.signals_json : [];
            const createdAt = run.created_at
              ? new Date(run.created_at).toLocaleString(undefined, {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : "";

            return (
              <div
                key={run.id}
                className="relative flex w-full items-start gap-3 text-left pl-2"
              >
                {/* Timeline dot */}
                <div
                  className={`relative z-10 mt-1.5 size-3 shrink-0 rounded-full border-2 ${
                    run.status === "completed"
                      ? "border-success bg-success/30"
                      : run.status === "failed"
                        ? "border-destructive bg-destructive/30"
                        : "border-muted-foreground bg-muted"
                  }`}
                />

                <div className="flex-1 min-w-0 rounded-2xl card-shadow p-2.5 hover:bg-muted/30 transition-colors">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-foreground truncate">
                        {decisionTitle ||
                          decisionAction?.replace(/_/g, " ") ||
                          run.top_signal_type?.replace(/_/g, " ") ||
                          run.trigger}
                      </p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        {createdAt} · {run.trigger}
                      </p>
                    </div>
                    {run.top_signal_type ? (
                      <div className="shrink-0 flex items-center gap-1">
                        <span
                          className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                            SIGNAL_COLORS[run.top_signal_type] ?? "bg-muted text-muted-foreground"
                          }`}
                        >
                          {run.top_signal_type.replace(/_/g, " ")}
                        </span>
                        <span
                          className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                            priority.level === "high"
                              ? "bg-destructive/20 text-destructive"
                              : priority.level === "medium"
                                ? "bg-warning/20 text-warning"
                                : "bg-muted text-muted-foreground"
                          }`}
                        >
                          {t(`agent.timeline.priority.${priority.level}`)}
                        </span>
                      </div>
                    ) : null}
                  </div>

                  {/* Signal pills */}
                  {signals.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {signals.slice(0, 5).map((sig, i) => (
                        <span
                          key={i}
                          className={`text-[9px] px-1 py-0.5 rounded ${
                            SIGNAL_COLORS[(sig as Record<string, unknown>).signal_type as string] ?? "bg-muted text-muted-foreground"
                          }`}
                        >
                          {((sig as Record<string, unknown>).signal_type as string)?.replace(/_/g, " ")}
                        </span>
                      ))}
                      {signals.length > 5 && (
                        <span className="text-[9px] px-1 py-0.5 rounded bg-muted text-muted-foreground">
                          +{signals.length - 5}
                        </span>
                      )}
                    </div>
                  )}

                  <div className="mt-2 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setExpandedId(isExpanded ? null : run.id)}
                      className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {isExpanded ? t("agent.timeline.collapse") : t("agent.timeline.expand")}
                    </button>
                    {quickPath ? (
                      <button
                        type="button"
                        onClick={() => router.push(quickPath)}
                        className="inline-flex items-center gap-1 text-[11px] text-brand hover:underline"
                      >
                        {t("agent.timeline.open")}
                        <ArrowRight className="size-3" />
                      </button>
                    ) : null}
                  </div>

                  {/* Expanded details */}
                  {isExpanded && decisionRecord && (
                    <div className="mt-2 pt-2 border-t border-border/60 space-y-1.5">
                      {decisionReason && (
                        <p className="text-[11px] text-muted-foreground">
                          <span className="font-medium text-foreground">{t("agent.timeline.reason")} </span>
                          {decisionReason}
                        </p>
                      )}
                      {decisionAction && (
                        <p className="text-[11px] text-muted-foreground">
                          <span className="font-medium text-foreground">{t("agent.timeline.action")} </span>
                          {decisionAction}
                        </p>
                      )}
                      {run.task_id && (
                        <p className="text-[11px] text-muted-foreground">
                          <span className="font-medium text-foreground">{t("agent.timeline.task")} </span>
                          {run.task_id}
                        </p>
                      )}
                      {run.error_message && (
                        <p className="text-[11px] text-destructive">
                          <span className="font-medium">{t("agent.timeline.error")} </span>
                          {run.error_message}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
