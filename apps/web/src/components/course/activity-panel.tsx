"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Clock3, FileClock, RotateCcw, ShieldCheck, Square, Workflow } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  approveAgentTask,
  cancelAgentTask,
  listAgentTasks,
  listChatSessions,
  listIngestionJobs,
  listPreferenceSignals,
  retryAgentTask,
  submitAgentTask,
  type AgentTask,
  type ChatSessionSummary,
  type IngestionJobSummary,
  type PreferenceSignal,
} from "@/lib/api";
import { toast } from "sonner";

interface ActivityPanelProps {
  courseId: string;
}

function formatTime(value: string | null): string {
  if (!value) return "Unknown time";
  return new Date(value).toLocaleString();
}

export function ActivityPanel({ courseId }: ActivityPanelProps) {
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [jobs, setJobs] = useState<IngestionJobSummary[]>([]);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [signals, setSignals] = useState<PreferenceSignal[]>([]);
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [nextTasks, nextJobs, nextSessions, nextSignals] = await Promise.all([
      listAgentTasks(courseId),
      listIngestionJobs(courseId),
      listChatSessions(courseId),
      listPreferenceSignals(courseId),
    ]);
    setTasks(nextTasks);
    setJobs(nextJobs);
    setSessions(nextSessions.slice(0, 5));
    setSignals(nextSignals.slice(0, 5));
  }, [courseId]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        await refresh();
      } catch {
        if (cancelled) return;
        setTasks([]);
        setJobs([]);
        setSessions([]);
        setSignals([]);
      }
    };
    void load();
    const timer = window.setInterval(() => {
      void load();
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refresh]);

  const mutateTask = async (taskId: string, action: "approve" | "cancel" | "retry") => {
    setBusyTaskId(taskId);
    try {
      if (action === "approve") {
        await approveAgentTask(taskId);
        toast.success("Task approved");
      } else if (action === "cancel") {
        await cancelAgentTask(taskId);
        toast.success("Task cancellation requested");
      } else {
        await retryAgentTask(taskId);
        toast.success("Task re-queued");
      }
      await refresh();
    } catch (error) {
      toast.error((error as Error).message || "Task update failed");
    } finally {
      setBusyTaskId(null);
    }
  };

  const queueExamPlan = async () => {
    setBusyTaskId("queue-exam-prep");
    try {
      await submitAgentTask({
        task_type: "exam_prep",
        title: "Queued exam prep plan",
        course_id: courseId,
        summary: "Run exam prep in the background from the activity queue.",
        input_json: { course_id: courseId, days_until_exam: 7 },
        source: "activity_panel",
        requires_approval: true,
        max_attempts: 2,
      });
      toast.success("Queued an exam-prep task for approval");
      await refresh();
    } catch (error) {
      toast.error((error as Error).message || "Failed to queue task");
    } finally {
      setBusyTaskId(null);
    }
  };

  return (
    <div className="flex-1 overflow-auto p-4 space-y-4" data-testid="activity-panel">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Workflow className="h-4 w-4 text-primary" />
            Agent Tasks
          </CardTitle>
          <CardDescription>Durable workflow outputs and agent-side work records.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between rounded-lg border border-dashed p-3">
            <div>
              <p className="text-sm font-medium">Queue exam-prep task</p>
              <p className="text-xs text-muted-foreground">Creates an approval-gated background task for this course.</p>
            </div>
            <Button size="sm" variant="outline" onClick={queueExamPlan} disabled={busyTaskId === "queue-exam-prep"}>
              <ShieldCheck className="mr-1 h-4 w-4" />
              Queue
            </Button>
          </div>
          {tasks.length === 0 && <p className="text-sm text-muted-foreground">No agent tasks yet.</p>}
          {tasks.map((task) => (
            <div key={task.id} className="rounded-lg border p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">{task.title}</p>
                  {task.summary && <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap">{task.summary}</p>}
                  {task.error_message && <p className="mt-1 text-xs text-red-600 whitespace-pre-wrap">{task.error_message}</p>}
                </div>
                <Badge variant="outline">{task.status}</Badge>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="outline">{task.task_type}</Badge>
                <Badge variant="outline">{task.source}</Badge>
                <Badge variant="outline">attempt {task.attempts}/{task.max_attempts}</Badge>
                <Badge variant="outline">{formatTime(task.completed_at || task.started_at || task.created_at)}</Badge>
              </div>
              {task.status === "awaiting_approval" && (
                <div className="mt-3 flex gap-2">
                  <Button size="sm" onClick={() => void mutateTask(task.id, "approve")} disabled={busyTaskId === task.id}>
                    <CheckCircle2 className="mr-1 h-4 w-4" />
                    Approve
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => void mutateTask(task.id, "cancel")} disabled={busyTaskId === task.id}>
                    <Square className="mr-1 h-4 w-4" />
                    Cancel
                  </Button>
                </div>
              )}
              {task.status === "running" && (
                <div className="mt-3">
                  <Button size="sm" variant="outline" onClick={() => void mutateTask(task.id, "cancel")} disabled={busyTaskId === task.id}>
                    <Square className="mr-1 h-4 w-4" />
                    Cancel
                  </Button>
                </div>
              )}
              {(task.status === "failed" || task.status === "cancelled") && (
                <div className="mt-3 flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => void mutateTask(task.id, "retry")} disabled={busyTaskId === task.id}>
                    <RotateCcw className="mr-1 h-4 w-4" />
                    Retry
                  </Button>
                </div>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <ShieldCheck className="h-4 w-4 text-primary" />
            Preference Learning
          </CardTitle>
          <CardDescription>Why OpenTutor inferred or updated learning preferences.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {signals.length === 0 && <p className="text-sm text-muted-foreground">No preference signals captured yet.</p>}
          {signals.map((signal) => (
            <div key={signal.id} className="rounded-lg border p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">
                    {signal.dimension}: {signal.value}
                  </p>
                  {signal.context?.evidence && (
                    <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap">{signal.context.evidence}</p>
                  )}
                  {signal.context?.user_message && (
                    <p className="mt-1 text-xs text-muted-foreground">From: {signal.context.user_message}</p>
                  )}
                </div>
                <Badge variant="outline">{signal.signal_type}</Badge>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="outline">{formatTime(signal.created_at)}</Badge>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <FileClock className="h-4 w-4 text-primary" />
            Ingestion Activity
          </CardTitle>
          <CardDescription>Recent uploads and scraped material processing.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {jobs.length === 0 && <p className="text-sm text-muted-foreground">No ingestion jobs yet.</p>}
          {jobs.map((job) => (
            <div key={job.id} className="rounded-lg border p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">{job.filename}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{job.category || "uncategorized"} via {job.source_type}</p>
                </div>
                <Badge variant="outline">{job.status}</Badge>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {job.dispatched_to && Object.entries(job.dispatched_to).map(([target, count]) => (
                  <Badge key={target} variant="outline">{target} {count}</Badge>
                ))}
                <Badge variant="outline">{formatTime(job.created_at)}</Badge>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Clock3 className="h-4 w-4 text-primary" />
            Recent Chat Sessions
          </CardTitle>
          <CardDescription>Conversation history that can be restored from the chat panel.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {sessions.length === 0 && <p className="text-sm text-muted-foreground">No chat sessions yet.</p>}
          {sessions.map((session) => (
            <div key={session.id} className="rounded-lg border p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">{session.title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {session.message_count} messages
                    {session.scene_id ? ` • ${session.scene_id}` : ""}
                  </p>
                </div>
                <Badge variant="outline">{formatTime(session.updated_at || session.created_at)}</Badge>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
