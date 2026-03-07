import { request } from "./client";

import type { JsonObject, NullableDateTime, SavedGeneratedAsset } from "./client";
import type { GeneratedAssetBatchSummary } from "./practice";

// ── Course Progress ──

interface LearningOverviewCourseSummary {
  course_id: string;
  course_name: string;
  average_mastery: number;
  study_minutes: number;
  wrong_answers: number;
  diagnosed_count: number;
  gap_types: Record<string, number>;
}

export interface CourseProgress {
  course_id: string;
  total_nodes: number;
  mastered: number;
  reviewed: number;
  in_progress: number;
  not_started: number;
  total_study_minutes: number;
  average_mastery: number;
  completion_percent: number;
  gap_type_breakdown: Record<string, number>;
}

export interface LearningOverview {
  total_courses: number;
  total_study_minutes: number;
  average_mastery: number;
  gap_type_breakdown: Record<string, number>;
  diagnosis_breakdown: Record<string, number>;
  error_category_breakdown: Record<string, number>;
  course_summaries: LearningOverviewCourseSummary[];
}

export async function getCourseProgress(courseId: string): Promise<CourseProgress> {
  return request(`/progress/courses/${courseId}`);
}

export async function getLearningOverview(): Promise<LearningOverview> {
  return request("/progress/overview");
}

// ── Trends ──

interface TrendDataPoint {
  date: string;
  study_minutes: number;
  quiz_total: number;
  quiz_correct: number;
  accuracy: number | null;
}

export interface LearningTrends {
  days: number;
  trend: TrendDataPoint[];
  current_mastery?: number;
  course_id?: string;
}

export async function getGlobalTrends(days = 30): Promise<LearningTrends> {
  return request(`/progress/trends?days=${days}`);
}

// ── Memory Stats ──

export interface MemoryStats {
  total: number;
  by_type: Record<string, number>;
  avg_importance: number;
  needs_consolidation: boolean;
  oldest_days: number;
  uncategorized: number;
  merged_count: number;
}

export async function getMemoryStats(courseId?: string): Promise<MemoryStats> {
  const params = courseId ? `?course_id=${courseId}` : "";
  return request(`/progress/memory-stats${params}`);
}

export async function triggerConsolidation(courseId?: string): Promise<Record<string, number>> {
  const params = courseId ? `?course_id=${courseId}` : "";
  return request(`/progress/memory-consolidate${params}`, { method: "POST" });
}

// ── Forgetting Forecast ──

export interface ForgettingPrediction {
  content_node_id: string | null;
  title: string;
  current_retrievability: number;
  stability_days: number;
  days_until_threshold: number;
  predicted_drop_date: string;
  urgency: "ok" | "warning" | "urgent" | "overdue";
  last_reviewed: string | null;
  mastery_score: number;
}

export interface ForgettingForecast {
  course_id: string;
  generated_at: string;
  total_items: number;
  urgent_count: number;
  warning_count: number;
  predictions: ForgettingPrediction[];
}

export async function getForgettingForecast(courseId: string): Promise<ForgettingForecast> {
  return request(`/progress/courses/${courseId}/forgetting-forecast`);
}

// ── Misconception Dashboard ──

export interface MisconceptionSample {
  question: string;
  user_answer: string;
  correct_answer: string;
  error_category: string | null;
  diagnosis: string | null;
}

export interface MisconceptionItem {
  concept: string;
  active_errors: number;
  total_errors: number;
  mastered_errors: number;
  resolution_rate: number;
  dominant_diagnosis: string | null;
  dominant_misconception_type: string | null;
  error_categories: Record<string, number>;
  priority_score: number;
  sample_questions: MisconceptionSample[];
}

export interface MisconceptionDashboard {
  course_id: string;
  misconceptions: MisconceptionItem[];
  summary: {
    total_concepts_with_issues: number;
    total_active_errors: number;
    total_resolved: number;
    resolution_rate: number;
    diagnosis_breakdown: Record<string, number>;
  };
}

export async function getMisconceptionDashboard(courseId: string): Promise<MisconceptionDashboard> {
  return request(`/progress/courses/${courseId}/misconceptions`);
}

// ── Knowledge Graph ──

export interface KnowledgeGraphNode {
  id: string;
  label: string;
  type?: string;
  level: number;
  size: number;
  color: string;
  status: string;
  mastery: number;
  gap_type?: string | null;
  x?: number;
  y?: number;
}

export interface KnowledgeGraphEdge {
  source: string;
  target: string;
  type: string;
}

interface KnowledgeGraphData {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
}

export async function getKnowledgeGraph(
  courseId: string,
): Promise<KnowledgeGraphData> {
  return request(`/progress/courses/${courseId}/knowledge-graph`);
}

// ── LECTOR Review Session ──

export interface ReviewItem {
  concept_id: string;
  concept_label: string;
  mastery: number;
  stability_days: number;
  retrievability: number;
  urgency: string;
  cluster: string | null;
  last_reviewed: string | null;
}

export interface ReviewSession {
  course_id: string;
  items: ReviewItem[];
  count: number;
}

export async function getReviewSession(
  courseId: string,
  maxItems = 10,
): Promise<ReviewSession> {
  return request(`/progress/courses/${courseId}/review-session?max_items=${maxItems}`);
}

export async function submitReviewRating(
  courseId: string,
  conceptId: string,
  rating: "again" | "hard" | "good" | "easy",
): Promise<{ concept_id: string; rating: string; new_mastery: number; new_stability_days: number }> {
  return request(`/progress/courses/${courseId}/review-session/rate`, {
    method: "POST",
    body: JSON.stringify({ concept_id: conceptId, rating }),
  });
}

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
  return request(`/tasks/${query}`);
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

// ── Learning Templates ──

interface LearningTemplate {
  id: string;
  name: string;
  description?: string;
  config: Record<string, unknown>;
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
