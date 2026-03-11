import { request } from "./client";

import type { JsonObject, NullableDateTime, SavedGeneratedAsset } from "./client";
import type { GeneratedAssetBatchSummary } from "./practice";

// ── Exam Prep & Study Plans ──

interface ExamPrepPlan {
  course: string;
  topics_count: number;
  readiness: Record<string, number>;
  days_until_exam: number;
  plan: string;
}

export async function getExamPrepPlan(
  courseId: string,
  daysUntilExam: number = 7,
  examTopic?: string,
): Promise<ExamPrepPlan> {
  return request("/workflows/exam-prep", {
    method: "POST",
    body: JSON.stringify({
      course_id: courseId,
      exam_topic: examTopic,
      days_until_exam: daysUntilExam,
    }),
  });
}

export async function saveStudyPlan(
  courseId: string,
  markdown: string,
  title?: string,
  replaceBatchId?: string,
): Promise<SavedGeneratedAsset> {
  return request("/workflows/study-plans/save", {
    method: "POST",
    body: JSON.stringify({
      course_id: courseId,
      markdown,
      title,
      replace_batch_id: replaceBatchId,
    }),
  });
}

export async function listStudyPlanBatches(courseId: string): Promise<GeneratedAssetBatchSummary[]> {
  return request(`/workflows/study-plans/${courseId}`);
}

export interface StudyPlanResponse {
  id: string;
  course_id: string;
  name: string;
  scene_id: string | null;
  tasks: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export async function getStudyPlans(courseId: string, limit = 5): Promise<StudyPlanResponse[]> {
  return request(`/workflows/courses/${courseId}/study-plans?limit=${limit}`);
}

// ── Agent Tasks ──

export interface AgentTask {
  id: string;
  user_id: string;
  course_id: string | null;
  goal_id: string | null;
  task_type: string;
  status:
    | "pending_approval"
    | "queued"
    | "running"
    | "cancel_requested"
    | "cancelled"
    | "failed"
    | "completed"
    | "resuming"
    | "rejected"
    | string;
  title: string;
  summary: string | null;
  source: string;
  input_json: JsonObject | null;
  metadata_json: JsonObject | null;
  result_json: JsonObject | null;
  error_message: string | null;
  attempts: number;
  max_attempts: number;
  requires_approval: boolean;
  task_kind: "read_only" | "content_mutation" | "notification" | "external_side_effect" | string;
  risk_level: "low" | "medium" | "high" | string;
  approval_status: "not_required" | "pending" | "approved" | "rejected" | string;
  approval_reason: string | null;
  approval_action: string | null;
  checkpoint_json: JsonObject | null;
  step_results: JsonObject[];
  provenance: JsonObject | null;
  approved_at: NullableDateTime;
  started_at: NullableDateTime;
  cancel_requested_at: NullableDateTime;
  created_at: NullableDateTime;
  updated_at: NullableDateTime;
  completed_at: NullableDateTime;
}

interface AgentTaskReviewGoalUpdate {
  goal_id: string;
  title: string;
  status: string;
  current_milestone: string | null;
  next_action: string | null;
}

interface AgentTaskReviewFollowUp {
  ready: boolean;
  label?: string | null;
  task_type?: string | null;
  title?: string | null;
  summary?: string | null;
  input_json?: JsonObject | null;
  plan_prompt?: string | null;
  auto_queued?: boolean;
  queued_task_id?: string | null;
}

export interface AgentTaskReview {
  status: string;
  outcome: string;
  blockers: string[];
  next_recommended_action: string | null;
  follow_up: AgentTaskReviewFollowUp;
  goal_update: AgentTaskReviewGoalUpdate | null;
}

export interface AgentTaskVerifierDiagnostics {
  request_coverage?: number;
  evidence_coverage?: number;
  request_overlap_terms?: string[];
  evidence_overlap_terms?: string[];
}

export interface AgentTaskStepResult {
  step_index?: number;
  step_type?: string;
  title?: string;
  success?: boolean;
  summary?: string;
  error?: string | null;
  verifier?: {
    status?: string;
    code?: string;
    message?: string;
  } | null;
  verifier_diagnostics?: AgentTaskVerifierDiagnostics | null;
}

export interface NextActionResponse {
  course_id: string;
  goal_id: string | null;
  title: string;
  reason: string;
  source: "deadline" | "task_failure" | "forgetting_risk" | "recent_goal" | "manual" | string;
  recommended_action: string;
  suggested_task_type: string | null;
  queue_label: string | null;
  queue_ready: boolean;
}

export async function listAgentTasks(courseId?: string): Promise<AgentTask[]> {
  const query = courseId ? `?course_id=${courseId}` : "";
  return request(`/tasks${query}`);
}

export async function submitAgentTask(body: {
  task_type: string;
  title: string;
  course_id?: string;
  goal_id?: string;
  summary?: string;
  input_json?: JsonObject;
  metadata_json?: JsonObject;
  source?: string;
  requires_approval?: boolean;
  max_attempts?: number;
}): Promise<AgentTask> {
  return request("/tasks/submit", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function approveAgentTask(taskId: string): Promise<AgentTask> {
  return request(`/tasks/${taskId}/approve`, { method: "POST" });
}

export async function rejectAgentTask(taskId: string): Promise<AgentTask> {
  return request(`/tasks/${taskId}/reject`, { method: "POST" });
}

// ── Study Goals ──

export interface StudyGoal {
  id: string;
  user_id: string;
  course_id: string | null;
  title: string;
  objective: string;
  success_metric: string | null;
  current_milestone: string | null;
  next_action: string | null;
  status: string;
  confidence: string | null;
  target_date: string | null;
  metadata_json: JsonObject | null;
  linked_task_count: number;
  created_at: NullableDateTime;
  updated_at: NullableDateTime;
  completed_at: NullableDateTime;
}

export async function listStudyGoals(courseId?: string, status?: string): Promise<StudyGoal[]> {
  const params = new URLSearchParams();
  if (courseId) params.set("course_id", courseId);
  if (status) params.set("status", status);
  const query = params.toString();
  return request(`/goals/${query ? `?${query}` : ""}`);
}

export async function getNextAction(courseId: string): Promise<NextActionResponse> {
  return request(`/goals/${courseId}/next-action`);
}

export interface CreateGoalRequest {
  title: string;
  objective: string;
  course_id?: string;
  success_metric?: string;
  current_milestone?: string;
  next_action?: string;
  status?: string;
  confidence?: string;
  target_date?: string;
  metadata_json?: JsonObject;
}

export interface UpdateGoalRequest {
  title?: string;
  objective?: string;
  success_metric?: string | null;
  current_milestone?: string | null;
  next_action?: string | null;
  status?: string;
  confidence?: string | null;
  target_date?: string | null;
  metadata_json?: JsonObject | null;
}

export async function createStudyGoal(body: CreateGoalRequest): Promise<StudyGoal> {
  return request("/goals/", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateStudyGoal(goalId: string, body: UpdateGoalRequest): Promise<StudyGoal> {
  return request(`/goals/${goalId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

// ── Agenda Runs ──

export interface AgendaRun {
  id: string;
  user_id: string;
  course_id: string | null;
  goal_id: string | null;
  trigger: string;
  status: string;
  top_signal_type: string | null;
  signals_json: Array<Record<string, unknown>> | Record<string, unknown> | null;
  decision_json: Record<string, unknown> | null;
  task_id: string | null;
  dedup_key: string | null;
  error_message: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export async function listAgendaRuns(courseId?: string, limit = 20): Promise<AgendaRun[]> {
  const params = new URLSearchParams();
  if (courseId) params.set("course_id", courseId);
  params.set("limit", String(limit));
  return request(`/agent/runs?${params.toString()}`);
}

export interface AgendaDecisionLogRequest {
  course_id?: string | null;
  goal_id?: string | null;
  trigger?: string;
  status?: string;
  top_signal_type?: string | null;
  action: string;
  title?: string;
  reason?: string;
  decision_type?: string;
  source?: string;
  metadata_json?: Record<string, unknown>;
  dedup_key?: string;
}

export async function logAgentDecision(body: AgendaDecisionLogRequest): Promise<AgendaRun> {
  return request("/agent/log-decision", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ── Learning Templates ──

export interface LearningTemplate {
  id: string;
  name: string;
  description?: string;
  config: Record<string, unknown>;
  is_builtin?: boolean;
  target_audience?: string;
  tags?: string[];
  preferences?: Record<string, string>;
}

export async function listTemplates(): Promise<LearningTemplate[]> {
  return request("/progress/templates");
}

export async function applyTemplate(templateId: string): Promise<void> {
  return request("/progress/templates/apply", {
    method: "POST",
    body: JSON.stringify({ template_id: templateId }),
  });
}

// ── Learning Science: Velocity ──

export interface VelocityResult {
  concepts_total: number;
  concepts_mastered: number;
  mastery_rate: number;
  avg_mastery: number;
  concepts_per_day: number;
  velocity_trend: string;
  window_days: number;
}

export async function getVelocity(
  courseId: string,
  windowDays?: number,
): Promise<VelocityResult> {
  const params = windowDays != null ? `?window_days=${windowDays}` : "";
  return request(`/progress/courses/${courseId}/velocity${params}`);
}

// ── Learning Science: Completion Forecast ──

export interface CompletionForecast {
  is_complete: boolean;
  concepts_remaining: number;
  avg_gap: number;
  optimistic_days: number;
  expected_days: number;
  pessimistic_days: number;
  optimistic_date: string | null;
  expected_date: string | null;
  pessimistic_date: string | null;
  confidence: number;
}

export async function getCompletionForecast(courseId: string): Promise<CompletionForecast> {
  return request(`/progress/courses/${courseId}/forecast`);
}

// ── Learning Science: Transfer Opportunities ──

export interface TransferOpportunity {
  source_concept: string;
  source_course_id: string;
  source_mastery: number;
  target_concept: string;
  target_course_id: string;
  target_mastery: number;
  edge_type: string;
  recommendation: string;
}

export async function getTransferOpportunities(): Promise<TransferOpportunity[]> {
  return request("/progress/transfer-opportunities");
}
