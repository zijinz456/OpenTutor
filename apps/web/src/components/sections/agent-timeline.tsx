"use client";

import { useEffect, useState } from "react";
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
};

interface AgentTimelineProps {
  courseId: string;
}

export function AgentTimeline({ courseId }: AgentTimelineProps) {
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
          {t("agent.timeline.empty") !== "agent.timeline.empty"
            ? t("agent.timeline.empty")
            : "No agent activity yet. The AI agent will start making decisions as you study."}
        </p>
      </div>
    );
  }

  const stats = {
    total: runs.length,
    completed: runs.filter((r) => r.status === "completed").length,
    signalTypes: new Set(runs.map((r) => r.top_signal_type).filter(Boolean)).size,
  };

  return (
    <div className="space-y-4">
      {/* Stats summary */}
      <div className="grid grid-cols-3 gap-2 px-4">
        <div className="rounded-lg bg-muted/50 p-2.5 text-center">
          <p className="text-lg font-semibold">{stats.total}</p>
          <p className="text-[10px] text-muted-foreground">
            {t("agent.timeline.totalRuns") !== "agent.timeline.totalRuns"
              ? t("agent.timeline.totalRuns")
              : "Total Runs"}
          </p>
        </div>
        <div className="rounded-lg bg-muted/50 p-2.5 text-center">
          <p className="text-lg font-semibold">{stats.completed}</p>
          <p className="text-[10px] text-muted-foreground">
            {t("agent.timeline.completed") !== "agent.timeline.completed"
              ? t("agent.timeline.completed")
              : "Completed"}
          </p>
        </div>
        <div className="rounded-lg bg-muted/50 p-2.5 text-center">
          <p className="text-lg font-semibold">{stats.signalTypes}</p>
          <p className="text-[10px] text-muted-foreground">
            {t("agent.timeline.signalTypes") !== "agent.timeline.signalTypes"
              ? t("agent.timeline.signalTypes")
              : "Signal Types"}
          </p>
        </div>
      </div>

      {/* Timeline */}
      <div className="relative px-4">
        <div className="absolute left-[27px] top-0 bottom-0 w-px bg-border" />
        <div className="space-y-3">
          {runs.map((run) => {
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
              <button
                type="button"
                key={run.id}
                onClick={() => setExpandedId(isExpanded ? null : run.id)}
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

                <div className="flex-1 min-w-0 rounded-lg border border-border p-2.5 hover:bg-muted/30 transition-colors">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-foreground truncate">
                        {decisionTitle ||
                          run.top_signal_type?.replace(/_/g, " ") ||
                          run.trigger}
                      </p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        {createdAt} · {run.trigger}
                      </p>
                    </div>
                    {run.top_signal_type ? (
                      <span
                        className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                          SIGNAL_COLORS[run.top_signal_type] ?? "bg-muted text-muted-foreground"
                        }`}
                      >
                        {run.top_signal_type.replace(/_/g, " ")}
                      </span>
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

                  {/* Expanded details */}
                  {isExpanded && decisionRecord && (
                    <div className="mt-2 pt-2 border-t border-border space-y-1.5">
                      {decisionReason && (
                        <p className="text-[11px] text-muted-foreground">
                          <span className="font-medium text-foreground">Reason: </span>
                          {decisionReason}
                        </p>
                      )}
                      {decisionAction && (
                        <p className="text-[11px] text-muted-foreground">
                          <span className="font-medium text-foreground">Action: </span>
                          {decisionAction}
                        </p>
                      )}
                      {run.task_id && (
                        <p className="text-[11px] text-muted-foreground">
                          <span className="font-medium text-foreground">Task: </span>
                          {run.task_id}
                        </p>
                      )}
                      {run.error_message && (
                        <p className="text-[11px] text-destructive">
                          <span className="font-medium">Error: </span>
                          {run.error_message}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
