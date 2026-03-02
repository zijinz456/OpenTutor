"use client";

import { useCallback, useEffect, useState } from "react";
import { useT } from "@/lib/i18n-context";
import {
  listAgentTasks,
  approveAgentTask,
  rejectAgentTask,
  listStudyGoals,
  type AgentTask,
  type StudyGoal,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface ActivityViewProps {
  courseId: string;
}

const STATUS_COLORS: Record<string, string> = {
  pending_approval: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  completed: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  queued: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
  cancelled: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
  rejected: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
};

function statusColor(status: string) {
  return STATUS_COLORS[status] ?? "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300";
}

export function ActivityView({ courseId }: ActivityViewProps) {
  const t = useT();

  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [goals, setGoals] = useState<StudyGoal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<Set<string>>(new Set());

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [t, g] = await Promise.all([
        listAgentTasks(courseId),
        listStudyGoals(courseId),
      ]);
      setTasks(t);
      setGoals(g);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const act = async (taskId: string, fn: (id: string) => Promise<AgentTask>) => {
    setActing((s) => new Set(s).add(taskId));
    try {
      const updated = await fn(taskId);
      setTasks((prev) => prev.map((tk) => (tk.id === taskId ? updated : tk)));
    } catch { /* keep current state */ } finally {
      setActing((s) => { const n = new Set(s); n.delete(taskId); return n; });
    }
  };

  if (loading) return (
    <div className="flex-1 flex items-center justify-center p-8">
      <p className="text-xs text-muted-foreground animate-pulse">Loading tasks...</p>
    </div>
  );
  if (error) return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 gap-2">
      <p className="text-xs text-destructive">{error}</p>
      <Button variant="outline" size="sm" onClick={fetchData}>Retry</Button>
    </div>
  );
  if (tasks.length === 0 && goals.length === 0) return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
      <h3 className="text-sm font-medium mb-1">{t("course.activity")}</h3>
      <p className="text-xs text-muted-foreground max-w-xs">
        No tasks or goals yet. Start a conversation and the agent will create tasks automatically.
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
    <div className="flex-1 flex flex-col gap-4 p-4 overflow-y-auto">
      {/* Pending approval */}
      {pending.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400 mb-2">
            Needs Approval ({pending.length})
          </h3>
          <div className="flex flex-col gap-2">
            {pending.map((tk) => (
              <div key={tk.id} className="rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/30 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{tk.title}</p>
                    {tk.summary && <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{tk.summary}</p>}
                    <p className="text-[10px] text-muted-foreground mt-1">{tk.task_type} &middot; {tk.source}</p>
                  </div>
                  <div className="flex gap-1.5 shrink-0">
                    <Button size="sm" disabled={acting.has(tk.id)} onClick={() => act(tk.id, approveAgentTask)}>Approve</Button>
                    <Button size="sm" variant="outline" disabled={acting.has(tk.id)} onClick={() => act(tk.id, rejectAgentTask)}>Reject</Button>
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
            <Badge variant="outline" className={statusColor(status)}>{status.replace("_", " ")}</Badge>
            <span>({grouped[status].length})</span>
          </h3>
          <div className="flex flex-col gap-1.5">
            {grouped[status].map((tk) => (
              <div key={tk.id} className="rounded-md border p-2.5 text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-medium truncate flex-1">{tk.title}</span>
                  <Badge variant="outline" className={statusColor(tk.status)}>{tk.status.replace("_", " ")}</Badge>
                </div>
                {tk.summary && <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{tk.summary}</p>}
                <p className="text-[10px] text-muted-foreground mt-1">{tk.task_type} &middot; {tk.source}</p>
              </div>
            ))}
          </div>
        </section>
      ))}

      {/* Goals */}
      {goals.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            Goals ({goals.length})
          </h3>
          <div className="flex flex-col gap-1.5">
            {goals.map((g) => (
              <div key={g.id} className="rounded-md border p-2.5">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium truncate flex-1">{g.title}</span>
                  <Badge variant="secondary" className="text-[10px]">{g.status}</Badge>
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">{g.objective}</p>
                {g.current_milestone && <p className="text-[10px] text-muted-foreground mt-1">Milestone: {g.current_milestone}</p>}
                {g.next_action && <p className="text-[10px] text-muted-foreground">Next: {g.next_action}</p>}
                {g.target_date && <p className="text-[10px] text-muted-foreground">Target: {g.target_date}</p>}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
