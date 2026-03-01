"use client";

import { useState } from "react";
import {
  CheckCircle2,
  Clock3,
  FileClock,
  PauseCircle,
  RotateCcw,
  ShieldCheck,
  Square,
  Workflow,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { ProvenanceBadges } from "@/components/provenance-badges";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useActivityPolling } from "@/hooks/use-activity-polling";
import {
  approveAgentTask,
  cancelAgentTask,
  createStudyGoal,
  rejectAgentTask,
  resumeAgentTask,
  retryAgentTask,
  submitAgentTask,
  updateStudyGoal,
  type AgentTask,
} from "@/lib/api";

interface ActivityPanelProps {
  courseId: string;
}

interface TaskStepProgress {
  step_index: number;
  title: string;
  status: string;
  summary?: string | null;
  agent?: string | null;
}

const RUNNING_STATUSES = new Set(["queued", "running", "resuming", "cancel_requested"]);
const COMPLETED_STATUSES = new Set(["completed", "failed", "cancelled", "rejected"]);

function formatTime(value: string | null): string {
  if (!value) return "Unknown time";
  return new Date(value).toLocaleString();
}

function formatLabel(value: string | null | undefined): string {
  if (!value) return "unknown";
  return value.replaceAll("_", " ");
}

function extractTaskSteps(task: AgentTask): TaskStepProgress[] {
  if (Array.isArray(task.step_results) && task.step_results.length > 0) {
    return task.step_results.map((rawStep) => ({
      step_index: Number(rawStep["step_index"] ?? 0),
      title: String(rawStep["title"] ?? `Step ${Number(rawStep["step_index"] ?? 0) + 1}`),
      status: String(
        rawStep["status"] ??
          (rawStep["summary"] === "Skipped — dependency not met."
            ? "skipped"
            : rawStep["success"]
              ? "completed"
              : "failed"),
      ),
      summary: typeof rawStep["summary"] === "string" ? rawStep["summary"] : null,
      agent: typeof rawStep["agent"] === "string" ? rawStep["agent"] : null,
    }));
  }

  const metadataSteps = task.metadata_json?.["plan_progress"];
  if (Array.isArray(metadataSteps)) {
    return metadataSteps as TaskStepProgress[];
  }

  const resultSteps = task.result_json?.["steps"];
  if (Array.isArray(resultSteps)) {
    return resultSteps.map((rawStep) => {
      const step = rawStep as Record<string, unknown>;
      return {
        step_index: Number(step["step_index"] ?? 0),
        title: String(step["title"] ?? `Step ${Number(step["step_index"] ?? 0) + 1}`),
        status: String(step["success"] ? "completed" : "failed"),
        summary: typeof step["summary"] === "string" ? step["summary"] : null,
        agent: typeof step["agent"] === "string" ? step["agent"] : null,
      };
    });
  }

  return [];
}

function StepList({ task }: { task: AgentTask }) {
  const steps = extractTaskSteps(task);
  if (steps.length === 0) return null;

  return (
    <div className="mt-3 rounded-md bg-muted/40 p-2">
      <p className="text-xs font-medium text-foreground/80">Step progress</p>
      <div className="mt-2 space-y-1.5">
        {steps.map((step) => (
          <div key={`${task.id}-${step.step_index}`} className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground/85">{step.title}</span>
            {` • ${formatLabel(step.status)}`}
            {step.agent ? ` • ${step.agent}` : ""}
            {step.summary ? ` • ${step.summary}` : ""}
          </div>
        ))}
      </div>
    </div>
  );
}

function TaskCard({
  task,
  busyTaskId,
  mutateTask,
  testIdPrefix = "agent-task",
  actionTestIdPrefix = "agent-task",
}: {
  task: AgentTask;
  busyTaskId: string | null;
  mutateTask: (taskId: string, action: "approve" | "reject" | "cancel" | "resume" | "retry") => Promise<void>;
  testIdPrefix?: string;
  actionTestIdPrefix?: string;
}) {
  const checkpoint = task.checkpoint_json ?? null;
  const showCancel = RUNNING_STATUSES.has(task.status);

  return (
    <div key={task.id} className="rounded-lg border p-3" data-testid={`${testIdPrefix}-${task.id}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium">{task.title}</p>
          {task.summary && <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap">{task.summary}</p>}
          {task.error_message && <p className="mt-1 text-xs text-red-600 whitespace-pre-wrap">{task.error_message}</p>}
          <ProvenanceBadges task={task} />
        </div>
        <Badge variant="outline">{formatLabel(task.status)}</Badge>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        <Badge variant="outline">{task.task_type}</Badge>
        <Badge variant="outline">{formatLabel(task.task_kind)}</Badge>
        <Badge variant="outline">{formatLabel(task.risk_level)} risk</Badge>
        <Badge variant="outline">{formatLabel(task.approval_status)}</Badge>
        <Badge variant="outline">{task.source}</Badge>
        <Badge variant="outline">attempt {task.attempts}/{task.max_attempts}</Badge>
        <Badge variant="outline">{formatTime(task.completed_at || task.started_at || task.created_at)}</Badge>
      </div>

      {checkpoint && (
        <div className="mt-3 rounded-md border border-dashed px-2.5 py-2 text-xs text-muted-foreground">
          Resume checkpoint:
          {" "}
          completed {String(checkpoint["completed_step_count"] ?? 0)}
          {" / "}
          failed {String(checkpoint["failed_step_count"] ?? 0)}
          {typeof checkpoint["last_success_summary"] === "string" && checkpoint["last_success_summary"]
            ? ` • ${checkpoint["last_success_summary"]}`
            : ""}
        </div>
      )}

      <StepList task={task} />

      {task.status === "pending_approval" && (
        <div className="mt-3 flex gap-2">
          <Button
            size="sm"
            data-testid={`${actionTestIdPrefix}-approve-${task.id}`}
            onClick={() => void mutateTask(task.id, "approve")}
            disabled={busyTaskId === task.id}
          >
            <CheckCircle2 className="mr-1 h-4 w-4" />
            Approve
          </Button>
          <Button
            size="sm"
            variant="outline"
            data-testid={`${actionTestIdPrefix}-reject-${task.id}`}
            onClick={() => void mutateTask(task.id, "reject")}
            disabled={busyTaskId === task.id}
          >
            <XCircle className="mr-1 h-4 w-4" />
            Reject
          </Button>
        </div>
      )}

      {showCancel && task.status !== "cancel_requested" && (
        <div className="mt-3">
          <Button
            size="sm"
            variant="outline"
            data-testid={`${actionTestIdPrefix}-cancel-${task.id}`}
            onClick={() => void mutateTask(task.id, "cancel")}
            disabled={busyTaskId === task.id}
          >
            <Square className="mr-1 h-4 w-4" />
            Cancel
          </Button>
        </div>
      )}

      {task.status === "cancel_requested" && (
        <div className="mt-3">
          <Badge variant="outline">
            <PauseCircle className="mr-1 h-3.5 w-3.5" />
            Cancelling after current step
          </Badge>
        </div>
      )}

      {task.status === "cancelled" && (
        <div className="mt-3 flex gap-2">
          <Button
            size="sm"
            data-testid={`${actionTestIdPrefix}-resume-${task.id}`}
            onClick={() => void mutateTask(task.id, "resume")}
            disabled={busyTaskId === task.id}
          >
            <CheckCircle2 className="mr-1 h-4 w-4" />
            Resume
          </Button>
          <Button
            size="sm"
            variant="outline"
            data-testid={`${actionTestIdPrefix}-retry-${task.id}`}
            onClick={() => void mutateTask(task.id, "retry")}
            disabled={busyTaskId === task.id}
          >
            <RotateCcw className="mr-1 h-4 w-4" />
            Retry
          </Button>
        </div>
      )}

      {(task.status === "failed" || task.status === "rejected") && (
        <div className="mt-3 flex gap-2">
          <Button
            size="sm"
            variant="outline"
            data-testid={`${actionTestIdPrefix}-retry-${task.id}`}
            onClick={() => void mutateTask(task.id, "retry")}
            disabled={busyTaskId === task.id}
          >
            <RotateCcw className="mr-1 h-4 w-4" />
            Retry
          </Button>
        </div>
      )}
    </div>
  );
}

export function ActivityPanel({ courseId }: ActivityPanelProps) {
  const { tasks, goals, jobs, sessions, signals, nextAction, refresh } = useActivityPolling(courseId);
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null);
  const [goalTitle, setGoalTitle] = useState("");
  const [goalObjective, setGoalObjective] = useState("");
  const [goalNextAction, setGoalNextAction] = useState("");

  const activeGoal = goals.find((goal) => goal.status === "active") ?? null;
  const inactiveGoals = goals.filter((goal) => goal.id !== activeGoal?.id);
  const pendingApprovals = tasks.filter((task) => task.status === "pending_approval");
  const runningTasks = tasks.filter((task) => RUNNING_STATUSES.has(task.status));
  const recentCompleted = tasks.filter((task) => COMPLETED_STATUSES.has(task.status)).slice(0, 6);

  const mutateTask = async (taskId: string, action: "approve" | "reject" | "cancel" | "resume" | "retry") => {
    setBusyTaskId(taskId);
    try {
      if (action === "approve") {
        await approveAgentTask(taskId);
        toast.success("Task approved");
      } else if (action === "reject") {
        await rejectAgentTask(taskId);
        toast.success("Task rejected");
      } else if (action === "cancel") {
        await cancelAgentTask(taskId);
        toast.success("Task cancellation requested");
      } else if (action === "resume") {
        await resumeAgentTask(taskId);
        toast.success("Task resumed");
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
        goal_id: activeGoal?.id,
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

  const createGoal = async () => {
    if (!goalTitle.trim() || !goalObjective.trim()) {
      toast.error("Goal title and objective are required");
      return;
    }
    setBusyTaskId("create-goal");
    try {
      await createStudyGoal({
        title: goalTitle.trim(),
        objective: goalObjective.trim(),
        course_id: courseId,
        next_action: goalNextAction.trim() || undefined,
        status: "active",
      });
      setGoalTitle("");
      setGoalObjective("");
      setGoalNextAction("");
      toast.success("Study goal created");
      await refresh();
    } catch (error) {
      toast.error((error as Error).message || "Failed to create goal");
    } finally {
      setBusyTaskId(null);
    }
  };

  const mutateGoalStatus = async (goalId: string, status: "active" | "paused" | "completed") => {
    setBusyTaskId(`goal:${goalId}:${status}`);
    try {
      await updateStudyGoal(goalId, { status });
      toast.success(status === "completed" ? "Study goal completed" : "Study goal updated");
      await refresh();
    } catch (error) {
      toast.error((error as Error).message || "Failed to update goal");
    } finally {
      setBusyTaskId(null);
    }
  };

  return (
    <div className="flex-1 space-y-4 overflow-auto p-4" data-testid="activity-panel">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <ShieldCheck className="h-4 w-4 text-primary" />
            Active Goal
          </CardTitle>
          <CardDescription>The durable objective the agent should optimize for.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="rounded-lg border border-dashed p-3 space-y-2">
            <Input
              data-testid="goal-title-input"
              value={goalTitle}
              onChange={(event) => setGoalTitle(event.target.value)}
              placeholder="Goal title"
            />
            <Textarea
              data-testid="goal-objective-input"
              value={goalObjective}
              onChange={(event) => setGoalObjective(event.target.value)}
              placeholder="What does success look like?"
              className="min-h-20"
            />
            <Input
              data-testid="goal-next-action-input"
              value={goalNextAction}
              onChange={(event) => setGoalNextAction(event.target.value)}
              placeholder="Next action (optional)"
            />
            <div className="flex justify-end">
              <Button size="sm" onClick={createGoal} disabled={busyTaskId === "create-goal"}>
                Create Goal
              </Button>
            </div>
          </div>

          {activeGoal ? (
            <div className="rounded-lg border p-3" data-testid={`study-goal-${activeGoal.id}`}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">{activeGoal.title}</p>
                  <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap">{activeGoal.objective}</p>
                  {activeGoal.next_action && (
                    <p className="mt-1 text-xs text-muted-foreground">Next action: {activeGoal.next_action}</p>
                  )}
                  {activeGoal.current_milestone && (
                    <p className="mt-1 text-xs text-muted-foreground">Milestone: {activeGoal.current_milestone}</p>
                  )}
                </div>
                <Badge variant="outline">{activeGoal.status}</Badge>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="outline">{activeGoal.linked_task_count} linked tasks</Badge>
                {activeGoal.target_date && <Badge variant="outline">Target {formatTime(activeGoal.target_date)}</Badge>}
                <Badge variant="outline">{formatTime(activeGoal.created_at)}</Badge>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  data-testid={`study-goal-complete-${activeGoal.id}`}
                  onClick={() => void mutateGoalStatus(activeGoal.id, "completed")}
                  disabled={busyTaskId === `goal:${activeGoal.id}:completed`}
                >
                  <CheckCircle2 className="mr-1 h-4 w-4" />
                  Complete
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  data-testid={`study-goal-pause-${activeGoal.id}`}
                  onClick={() => void mutateGoalStatus(activeGoal.id, "paused")}
                  disabled={busyTaskId === `goal:${activeGoal.id}:paused`}
                >
                  <PauseCircle className="mr-1 h-4 w-4" />
                  Pause
                </Button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No active goal yet.</p>
          )}

          {inactiveGoals.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Other goals</p>
              {inactiveGoals.map((goal) => (
                <div key={goal.id} className="rounded-lg border p-3" data-testid={`study-goal-${goal.id}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium">{goal.title}</p>
                      <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap">{goal.objective}</p>
                    </div>
                    <Badge variant="outline">{goal.status}</Badge>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {goal.status !== "active" && goal.status !== "completed" && (
                      <Button
                        size="sm"
                        variant="outline"
                        data-testid={`study-goal-activate-${goal.id}`}
                        onClick={() => void mutateGoalStatus(goal.id, "active")}
                        disabled={busyTaskId === `goal:${goal.id}:active`}
                      >
                        <RotateCcw className="mr-1 h-4 w-4" />
                        Activate
                      </Button>
                    )}
                    {goal.status !== "completed" && (
                      <Button
                        size="sm"
                        variant="outline"
                        data-testid={`study-goal-complete-${goal.id}`}
                        onClick={() => void mutateGoalStatus(goal.id, "completed")}
                        disabled={busyTaskId === `goal:${goal.id}:completed`}
                      >
                        <CheckCircle2 className="mr-1 h-4 w-4" />
                        Complete
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {nextAction && (
            <div className="rounded-lg border border-primary/20 bg-primary/5 p-3">
              <p className="text-xs font-medium uppercase tracking-wide text-primary">Next Best Action</p>
              <p className="mt-1 text-sm font-medium text-foreground">{nextAction.title}</p>
              <p className="mt-1 text-xs text-muted-foreground">{nextAction.reason}</p>
              <p className="mt-2 text-sm text-foreground/90">{nextAction.recommended_action}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="outline">{formatLabel(nextAction.source)}</Badge>
                {nextAction.suggested_task_type && (
                  <Badge variant="outline">{nextAction.suggested_task_type}</Badge>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <ShieldCheck className="h-4 w-4 text-primary" />
            Pending Approvals
          </CardTitle>
          <CardDescription>Actions blocked until you explicitly approve them.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {pendingApprovals.length === 0 && <p className="text-sm text-muted-foreground">No approvals pending.</p>}
          {pendingApprovals.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              busyTaskId={busyTaskId}
              mutateTask={mutateTask}
              testIdPrefix="approval-inbox-task"
              actionTestIdPrefix="approval-inbox"
            />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Workflow className="h-4 w-4 text-primary" />
            Running Tasks
          </CardTitle>
          <CardDescription>Durable work the agent is currently executing or preparing to resume.</CardDescription>
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
          {runningTasks.length === 0 && <p className="text-sm text-muted-foreground">No running tasks right now.</p>}
          {runningTasks.map((task) => (
            <TaskCard key={task.id} task={task} busyTaskId={busyTaskId} mutateTask={mutateTask} />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <CheckCircle2 className="h-4 w-4 text-primary" />
            Recent Completed
          </CardTitle>
          <CardDescription>Recent task outcomes, including failures and recoverable cancellations.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {recentCompleted.length === 0 && <p className="text-sm text-muted-foreground">No completed task history yet.</p>}
          {recentCompleted.map((task) => (
            <TaskCard key={task.id} task={task} busyTaskId={busyTaskId} mutateTask={mutateTask} />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <FileClock className="h-4 w-4 text-primary" />
            Ingestion Jobs
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
                  <p className="mt-1 text-xs text-muted-foreground">
                    {job.category || "uncategorized"} via {job.source_type}
                  </p>
                  {job.phase_label && <p className="mt-1 text-xs text-muted-foreground">{job.phase_label}</p>}
                  {job.error_message && <p className="mt-1 text-xs text-red-600">{job.error_message}</p>}
                </div>
                <Badge variant="outline">{formatLabel(job.status)}</Badge>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="outline">{job.progress_percent}%</Badge>
                <Badge variant="outline">embedding {formatLabel(job.embedding_status)}</Badge>
                <Badge variant="outline">{job.nodes_created} nodes</Badge>
                <Badge variant="outline">{formatTime(job.updated_at || job.created_at)}</Badge>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Clock3 className="h-4 w-4 text-primary" />
            Recent Sessions
          </CardTitle>
          <CardDescription>Conversation context that can be restored from chat.</CardDescription>
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

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <ShieldCheck className="h-4 w-4 text-primary" />
            Preference Signals
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
    </div>
  );
}
