import { request } from "./client";

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

// ── Weekly Report ──

interface WeekStats {
  study_minutes: number;
  active_days: number;
  quiz_total: number;
  quiz_correct: number;
  accuracy: number;
}

export interface WeeklyReport {
  period: { start: string; end: string };
  this_week: WeekStats;
  last_week: WeekStats;
  deltas: { study_minutes: number; accuracy: number; quiz_total: number };
  mastery_avg: number;
  highlights: string[];
}

export async function getWeeklyReport(): Promise<WeeklyReport> {
  return request("/progress/weekly-report");
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

// ── Re-export everything from progress-analytics ──

export {
  getExamPrepPlan,
  saveStudyPlan,
  listStudyPlanBatches,
  getStudyPlans,
  listAgentTasks,
  submitAgentTask,
  approveAgentTask,
  rejectAgentTask,
  listStudyGoals,
  createStudyGoal,
  updateStudyGoal,
  getNextAction,
  listAgendaRuns,
  logAgentDecision,
  listTemplates,
  applyTemplate,
  getVelocity,
  getCompletionForecast,
  getTransferOpportunities,
} from "./progress-analytics";

export type {
  StudyPlanResponse,
  AgentTask,
  AgentTaskReview,
  AgentTaskVerifierDiagnostics,
  AgentTaskStepResult,
  LearningTemplate,
  NextActionResponse,
  StudyGoal,
  CreateGoalRequest,
  UpdateGoalRequest,
  AgendaRun,
  AgendaDecisionLogRequest,
  VelocityResult,
  CompletionForecast,
  TransferOpportunity,
} from "./progress-analytics";
