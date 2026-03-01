/**
 * API client for OpenTutor backend.
 *
 * Simple fetch-based client. Phase 1 may upgrade to tRPC or orpc.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error: ${res.status}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

// ── Courses ──

export interface Course {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface HealthStatus {
  status: string;
  version: string;
  llm_providers: string[];
  llm_primary: string | null;
  llm_required: boolean;
  llm_available: boolean;
  llm_status: "configuration_required" | "mock_fallback" | "degraded" | "ready";
  llm_provider_health: Record<string, boolean>;
}

export interface LlmRuntimeProviderStatus {
  provider: string;
  has_key: boolean;
  masked_key: string | null;
}

export interface LlmRuntimeConfig {
  provider: string;
  model: string;
  llm_required: boolean;
  providers: LlmRuntimeProviderStatus[];
}

export interface LlmConnectionTestResult {
  provider: string;
  model: string;
  ok: boolean;
  response_preview: string;
  usage: Record<string, number>;
}

export async function listCourses(): Promise<Course[]> {
  return request("/courses/");
}

export async function getHealthStatus(): Promise<HealthStatus> {
  return request("/health");
}

export async function getLlmRuntimeConfig(): Promise<LlmRuntimeConfig> {
  return request("/preferences/runtime/llm");
}

export async function updateLlmRuntimeConfig(body: {
  provider?: string;
  model?: string;
  llm_required?: boolean;
  provider_keys?: Record<string, string>;
}): Promise<LlmRuntimeConfig> {
  return request("/preferences/runtime/llm", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function testLlmRuntimeConnection(body: {
  provider: string;
  model?: string;
  api_key?: string;
}): Promise<LlmConnectionTestResult> {
  return request("/preferences/runtime/llm/test", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function createCourse(name: string, description?: string): Promise<Course> {
  return request("/courses/", {
    method: "POST",
    body: JSON.stringify({ name, description }),
  });
}

export async function deleteCourse(id: string): Promise<void> {
  await request<void>(`/courses/${id}`, { method: "DELETE" });
}

// ── Content ──

export interface ContentNode {
  id: string;
  title: string;
  content: string | null;
  level: number;
  order_index: number;
  source_type: string;
  children: ContentNode[];
}

export async function getContentTree(courseId: string): Promise<ContentNode[]> {
  return request(`/courses/${courseId}/content-tree`);
}

export interface RestructuredNotes {
  original_title: string;
  ai_content: string;
  format_used: string;
}

export async function restructureNotes(
  contentNodeId: string,
  formatOverride?: string,
): Promise<RestructuredNotes> {
  return request("/notes/restructure", {
    method: "POST",
    body: JSON.stringify({
      content_node_id: contentNodeId,
      format_override: formatOverride,
    }),
  });
}

export async function saveGeneratedNotes(
  courseId: string,
  markdown: string,
  title: string,
  sourceNodeId?: string,
  replaceBatchId?: string,
): Promise<{ id: string; batch_id: string; version: number; replaced: boolean }> {
  return request("/notes/generated/save", {
    method: "POST",
    body: JSON.stringify({
      course_id: courseId,
      markdown,
      title,
      source_node_id: sourceNodeId,
      replace_batch_id: replaceBatchId,
    }),
  });
}

export async function listGeneratedNoteBatches(courseId: string): Promise<GeneratedAssetBatchSummary[]> {
  return request(`/notes/generated/${courseId}`);
}

export async function uploadFile(courseId: string, file: File): Promise<{ nodes_created: number }> {
  const form = new FormData();
  form.append("file", file);
  form.append("course_id", courseId);

  const res = await fetch(`${API_BASE}/content/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || "Upload failed");
  }
  return res.json();
}

export async function scrapeUrl(courseId: string, url: string): Promise<{ nodes_created: number }> {
  const form = new FormData();
  form.append("url", url);
  form.append("course_id", courseId);

  const res = await fetch(`${API_BASE}/content/url`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || "Scrape failed");
  }
  return res.json();
}

// ── Chat (SSE streaming) ──

export type ChatActionType =
  | "set_layout_preset"
  | "set_preference"
  | "suggest_scene_switch"
  | "switch_tab"
  | "open_flashcards"
  | "load_wrong_answers"
  | "generate_study_plan"
  | "set_note_format";

export interface ChatAction {
  action: ChatActionType | string;  // Known actions + extensible
  value?: string;
  extra?: string;
}

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatSessionSummary {
  id: string;
  course_id: string;
  scene_id: string | null;
  title: string;
  created_at: string | null;
  updated_at: string | null;
  message_count: number;
}

export interface PersistedChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  metadata_json?: ChatMessageMetadata | null;
  created_at: string | null;
}

export interface ChatSceneExplanation {
  scene?: string;
  mode?: string;
  matched_text?: string | null;
  current_scene?: string;
  target_scene?: string;
  matched_keywords?: string[];
  reason?: string;
}

export interface ChatPreferenceDetail {
  dimension: string;
  value: string;
  source: string;
}

export interface ChatContentReference {
  title?: string;
  source_type?: string;
  preview?: string;
}

export interface ChatProvenance {
  scene?: string;
  scene_resolution?: ChatSceneExplanation;
  scene_switch?: ChatSceneExplanation;
  preferences_applied?: string[];
  preference_sources?: Record<string, string>;
  preference_details?: ChatPreferenceDetail[];
  content_count?: number;
  content_titles?: string[];
  content_refs?: ChatContentReference[];
  memory_count?: number;
  tool_count?: number;
  tool_names?: string[];
  action_count?: number;
}

export interface ChatMessageMetadata {
  agent?: string;
  intent?: string;
  tokens?: number;
  actions?: ChatAction[];
  reflection?: Record<string, unknown> | null;
  provenance?: ChatProvenance | null;
}

export type StreamEvent =
  | { type: "content"; content: string }
  | { type: "action"; action: ChatAction }
  | { type: "status"; phase: string; intent?: string; confidence?: number; agent?: string }
  | { type: "replace"; content: string }
  | { type: "tool_status"; status: "running" | "complete"; tool: string }
  | { type: "done"; sessionId?: string; agent?: string; intent?: string; tokens?: number; metadata?: ChatMessageMetadata };

export interface ImageAttachment {
  data: string;       // base64-encoded
  media_type: string; // "image/png" | "image/jpeg" | "image/webp"
  filename?: string;
}

export interface ChatStreamOptions {
  courseId: string;
  message: string;
  activeTab?: string;
  tabContext?: Record<string, unknown>;
  scene?: string;
  sessionId?: string;
  history?: ChatHistoryMessage[];
  signal?: AbortSignal;
  images?: ImageAttachment[];
}

export async function* streamChat(
  courseIdOrOptions: string | ChatStreamOptions,
  message?: string,
): AsyncGenerator<StreamEvent, void, unknown> {
  // Support both legacy (courseId, message) and new options-based signature
  const opts: ChatStreamOptions =
    typeof courseIdOrOptions === "string"
      ? { courseId: courseIdOrOptions, message: message! }
      : courseIdOrOptions;

  const res = await fetch(`${API_BASE}/chat/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      course_id: opts.courseId,
      message: opts.message,
      active_tab: opts.activeTab,
      tab_context: opts.tabContext,
      scene: opts.scene,
      session_id: opts.sessionId,
      history: opts.history ?? [],
      images: opts.images ?? [],
    }),
    signal: opts.signal,
  });

  if (!res.ok || !res.body) {
    const error = await res.json().catch(() => ({ detail: "Chat stream failed" }));
    throw new Error(error.detail || "Chat stream failed");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let lastEventName = "message";
  const findEventBoundary = (input: string): number => {
    const crlfIndex = input.indexOf("\r\n\r\n");
    const lfIndex = input.indexOf("\n\n");
    if (crlfIndex === -1) return lfIndex;
    if (lfIndex === -1) return crlfIndex;
    return Math.min(crlfIndex, lfIndex);
  };

  const consumeEventBlock = async function* (rawBlock: string): AsyncGenerator<StreamEvent, void, unknown> {
    const eventBlock = rawBlock.replace(/\r/g, "");
    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of eventBlock.split("\n")) {
      if (line.startsWith("event: ")) {
        eventName = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        dataLines.push(line.slice(6));
      }
    }

    if (!dataLines.length) {
      lastEventName = eventName || lastEventName;
      return;
    }

    const resolvedEvent = eventName || lastEventName;
    lastEventName = resolvedEvent;

    try {
      const data = JSON.parse(dataLines.join("\n"));
      if (resolvedEvent === "message" && data.content) {
        yield { type: "content", content: data.content };
      } else if (resolvedEvent === "action" && data.action) {
        yield { type: "action", action: data as ChatAction };
      } else if (resolvedEvent === "status") {
        yield {
          type: "status",
          phase: data.phase,
          intent: data.intent,
          confidence: data.confidence,
          agent: data.agent,
        };
      } else if (resolvedEvent === "replace" && data.content) {
        yield { type: "replace", content: data.content };
      } else if (resolvedEvent === "tool_status") {
        yield {
          type: "tool_status",
          status: data.status,
          tool: data.tool,
        };
      } else if (resolvedEvent === "done") {
        yield {
          type: "done",
          sessionId: data.session_id,
          agent: data.agent,
          intent: data.intent,
          tokens: data.tokens,
          metadata: {
            agent: data.agent,
            intent: data.intent,
            tokens: data.tokens,
            actions: data.actions,
            provenance: data.provenance,
            reflection: data.reflection,
          },
        };
      } else if (resolvedEvent === "error" && data.error) {
        throw new Error(data.error);
      }
    } catch (error) {
      if (error instanceof Error) {
        throw error;
      }
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    let boundary = findEventBoundary(buffer);
    while (boundary !== -1) {
      const separatorLength = buffer.slice(boundary, boundary + 4) === "\r\n\r\n" ? 4 : 2;
      const eventBlock = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + separatorLength);
      for await (const parsedEvent of consumeEventBlock(eventBlock)) {
        yield parsedEvent;
      }
      boundary = findEventBoundary(buffer);
    }

    if (done) {
      const trailing = buffer.trim();
      if (trailing) {
        for await (const parsedEvent of consumeEventBlock(trailing)) {
          yield parsedEvent;
        }
      }
      break;
    }
  }
}

export async function listChatSessions(courseId: string): Promise<ChatSessionSummary[]> {
  return request(`/chat/courses/${courseId}/sessions`);
}

export async function getChatSessionMessages(
  sessionId: string,
): Promise<{ session: ChatSessionSummary; messages: PersistedChatMessage[] }> {
  return request(`/chat/sessions/${sessionId}/messages`);
}

// ── Preferences ──

export interface Preference {
  id: string;
  dimension: string;
  value: string;
  scope: string;
  source: string;
  confidence: number;
  course_id: string | null;
  updated_at: string;
}

export interface ResolvedPreferences {
  preferences: Record<string, string>;
  sources: Record<string, string>;
}

export async function listPreferences(): Promise<Preference[]> {
  return request("/preferences/");
}

export async function setPreference(
  dimension: string,
  value: string,
  scope: string = "global",
  courseId?: string,
  source: string = "onboarding",
): Promise<Preference> {
  return request("/preferences/", {
    method: "POST",
    body: JSON.stringify({
      dimension,
      value,
      scope,
      course_id: courseId,
      source,
    }),
  });
}

export async function resolvePreferences(courseId?: string): Promise<ResolvedPreferences> {
  const params = courseId ? `?course_id=${courseId}` : "";
  return request(`/preferences/resolve${params}`);
}

// ── Scenes ──

export interface SceneConfig {
  scene_id: string;
  display_name: string;
  icon: string | null;
  tab_preset: Array<{ type: string; position: number }>;
  workflow: string;
  ai_behavior: Record<string, unknown>;
  preferences: Record<string, string> | null;
}

export interface ActiveSceneResult {
  scene_id: string;
  config: SceneConfig;
  snapshot: Record<string, unknown> | null;
}

export interface SwitchResult {
  switched: boolean;
  scene_id: string;
  from_scene?: string;
  config: SceneConfig;
  tab_layout?: Array<{ type: string; position: number }>;
  init_actions: Array<{ type: string; action: string; message: string }>;
  message?: string;
  explanation?: {
    workflow?: string;
    recommended_tabs?: string[];
    reason?: string;
  };
}

export async function listScenes(): Promise<SceneConfig[]> {
  return request("/scenes/");
}

export async function getActiveScene(courseId: string): Promise<ActiveSceneResult> {
  return request(`/scenes/${courseId}/active`);
}

export async function switchScene(
  courseId: string,
  sceneId: string,
  currentUiState?: Record<string, unknown>,
): Promise<SwitchResult> {
  return request(`/scenes/${courseId}/switch`, {
    method: "POST",
    body: JSON.stringify({
      scene_id: sceneId,
      current_ui_state: currentUiState,
    }),
  });
}

// ── Wrong Answers ──

export interface WrongAnswer {
  id: string;
  problem_id: string;
  question: string | null;
  question_type: string | null;
  user_answer: string;
  correct_answer: string | null;
  explanation: string | null;
  error_category: string | null;
  diagnosis: string | null;
  error_detail: {
    category?: string;
    confidence?: number;
    evidence?: string;
    related_concept?: string;
    diagnosis?: string;
    original_correct?: boolean;
    clean_correct?: boolean;
    diagnostic_problem_id?: string;
  } | null;
  knowledge_points: string[] | null;
  review_count: number;
  mastered: boolean;
}

export async function listWrongAnswers(
  courseId: string,
  params?: { mastered?: boolean; error_category?: string },
): Promise<WrongAnswer[]> {
  const search = new URLSearchParams();
  if (params?.mastered !== undefined) search.set("mastered", String(params.mastered));
  if (params?.error_category) search.set("error_category", params.error_category);
  const qs = search.toString();
  return request(`/wrong-answers/${courseId}${qs ? `?${qs}` : ""}`);
}

export async function retryWrongAnswer(id: string, userAnswer: string) {
  return request<{ is_correct: boolean; correct_answer: string | null; explanation: string | null }>(
    `/wrong-answers/${id}/retry`,
    { method: "POST", body: JSON.stringify({ user_answer: userAnswer }) },
  );
}

export async function deriveQuestion(id: string) {
  return request<{
    problem_id: string;
    question: string;
    question_type: string;
    options: Record<string, string> | null;
    correct_answer: string | null;
    explanation: string | null;
  }>(
    `/wrong-answers/${id}/derive`,
    { method: "POST" },
  );
}

export async function diagnoseWrongAnswer(id: string): Promise<{
  diagnosis?: string;
  original_correct?: boolean;
  clean_correct?: boolean | null;
  interpretation?: string;
  status?: string;
  diagnostic_problem_id?: string;
  message?: string;
}> {
  return request(`/wrong-answers/${id}/diagnose`, {
    method: "POST",
  });
}

export async function getWrongAnswerStats(
  courseId: string,
): Promise<{
  total: number;
  mastered: number;
  unmastered: number;
  by_category: Record<string, number>;
  by_diagnosis: Record<string, number>;
}> {
  return request(`/wrong-answers/${courseId}/stats`);
}

export interface QuizProblem {
  id: string;
  question_type: string;
  question: string;
  options: Record<string, string> | null;
  order_index: number;
}

export interface GeneratedQuizDraft {
  question_type: string;
  question: string;
  options: Record<string, string> | null;
  correct_answer?: string | null;
  explanation?: string | null;
  difficulty_layer?: number | null;
  problem_metadata?: Record<string, unknown> | null;
}

export interface GeneratedQuizBatchSummary {
  batch_id: string;
  title: string;
  current_version: number;
  problem_count: number;
  is_active: boolean;
  updated_at: string | null;
}

export interface GeneratedAssetBatchSummary {
  batch_id: string;
  title: string;
  current_version: number;
  is_active: boolean;
  updated_at: string | null;
  asset_count: number;
  preview: Record<string, unknown>;
}

export interface AnswerResult {
  is_correct: boolean;
  correct_answer: string | null;
  explanation: string | null;
}

export async function listProblems(courseId: string): Promise<QuizProblem[]> {
  return request(`/quiz/${courseId}`);
}

export function parseGeneratedQuizDraft(rawContent: string): GeneratedQuizDraft[] {
  const trimmed = rawContent.trim();
  const candidates = [trimmed];
  const start = rawContent.indexOf("[");
  const end = rawContent.lastIndexOf("]");
  if (start >= 0 && end > start) {
    candidates.push(rawContent.slice(start, end + 1));
  }
  for (const candidate of candidates) {
    const normalized = candidate.startsWith("```")
      ? candidate.split("\n").slice(1, -1).join("\n")
      : candidate;
    try {
      const parsed = JSON.parse(normalized);
      if (
        Array.isArray(parsed) &&
        parsed.every((item) => item && typeof item.question === "string" && typeof item.question_type === "string")
      ) {
        return parsed as GeneratedQuizDraft[];
      }
    } catch {
      // Try next candidate.
    }
  }
  return [];
}

export async function extractQuiz(courseId: string): Promise<{ problems_created: number }> {
  return request("/quiz/extract", {
    method: "POST",
    body: JSON.stringify({ course_id: courseId }),
  });
}

export async function saveGeneratedQuiz(
  courseId: string,
  rawContent: string,
  title?: string,
  replaceBatchId?: string,
): Promise<{ saved: number; problem_ids: string[]; batch_id: string; version: number; replaced: boolean }> {
  return request("/quiz/save-generated", {
    method: "POST",
    body: JSON.stringify({
      course_id: courseId,
      raw_content: rawContent,
      title,
      replace_batch_id: replaceBatchId,
    }),
  });
}

export async function listGeneratedQuizBatches(courseId: string): Promise<GeneratedQuizBatchSummary[]> {
  return request(`/quiz/${courseId}/generated-batches`);
}

export async function submitAnswer(problemId: string, answer: string): Promise<AnswerResult> {
  return request("/quiz/submit", {
    method: "POST",
    body: JSON.stringify({ problem_id: problemId, user_answer: answer }),
  });
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
  course_summaries: Array<{
    course_id: string;
    course_name: string;
    average_mastery: number;
    study_minutes: number;
    wrong_answers: number;
    diagnosed_count: number;
    gap_types: Record<string, number>;
  }>;
}

export async function getCourseProgress(courseId: string): Promise<CourseProgress> {
  return request(`/progress/courses/${courseId}`);
}

export async function getLearningOverview(): Promise<LearningOverview> {
  return request("/progress/overview");
}

export interface TrendDataPoint {
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

export async function getCourseTrends(courseId: string, days = 30): Promise<LearningTrends> {
  return request(`/progress/courses/${courseId}/trends?days=${days}`);
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

export interface Flashcard {
  id: string;
  front: string;
  back: string;
  difficulty: string;
  fsrs: {
    difficulty: number;
    stability: number;
    reps: number;
    state: string;
    due: string | null;
    last_review?: string | null;
  };
}

export async function generateFlashcards(
  courseId: string,
  count: number = 10,
): Promise<{ cards: Flashcard[]; count: number }> {
  return request("/flashcards/generate", {
    method: "POST",
    body: JSON.stringify({ course_id: courseId, count }),
  });
}

export async function saveGeneratedFlashcards(
  courseId: string,
  cards: Flashcard[],
  title?: string,
  replaceBatchId?: string,
): Promise<{ id: string; batch_id: string; version: number; replaced: boolean }> {
  return request("/flashcards/generated/save", {
    method: "POST",
    body: JSON.stringify({
      course_id: courseId,
      cards,
      title,
      replace_batch_id: replaceBatchId,
    }),
  });
}

export async function listGeneratedFlashcardBatches(courseId: string): Promise<GeneratedAssetBatchSummary[]> {
  return request(`/flashcards/generated/${courseId}`);
}

export async function reviewFlashcard(
  card: Flashcard,
  rating: number,
): Promise<{ card: Flashcard; next_review: string | null }> {
  return request("/flashcards/review", {
    method: "POST",
    body: JSON.stringify({ card, rating }),
  });
}

export interface KnowledgeGraphNode {
  id: string;
  label: string;
  level: number;
  size: number;
  color: string;
  status: string;
  mastery: number;
  x?: number;
  y?: number;
}

export interface KnowledgeGraphEdge {
  source: string;
  target: string;
  type: string;
}

export async function getKnowledgeGraph(
  courseId: string,
): Promise<{ nodes: KnowledgeGraphNode[]; edges: KnowledgeGraphEdge[] }> {
  return request(`/progress/courses/${courseId}/knowledge-graph`);
}

// ── Learning Path Optimization ──

export interface LearningPathNode {
  id: string;
  name: string;
  description: string | null;
  mastery: number;
  estimated_minutes: number;
  priority: number;
  on_critical_path: boolean;
  depth: number;
  prerequisites: string[];
}

export interface LearningPath {
  path: LearningPathNode[];
  critical_path: { id: string; name: string; mastery: number; estimated_minutes: number }[];
  critical_path_minutes: number;
  parallel_groups: { id: string; name: string }[][];
  total_estimated_minutes: number;
  skipped_mastered: number;
  total_knowledge_points: number;
  cycle_detected: boolean;
}

export async function getOptimizedLearningPath(
  courseId: string,
  skipMastered = true,
): Promise<LearningPath> {
  return request(`/progress/courses/${courseId}/learning-path?skip_mastered=${skipMastered}`);
}

export async function getWrongAnswerReview(
  courseId: string,
): Promise<{ review: string; wrong_answer_count: number; wrong_answer_ids: string[] }> {
  return request(`/workflows/wrong-answer-review?course_id=${courseId}`);
}

export function getFileUrl(jobId: string): string {
  return `${API_BASE}/content/files/${jobId}`;
}

export interface UploadedCourseFile {
  id: string;
  job_id?: string;
  filename: string;
  file_name?: string;
  mime_type: string | null;
  created_at: string | null;
}

export interface IngestionJobSummary {
  id: string;
  filename: string;
  source_type: string;
  category: string | null;
  status: string;
  dispatched_to: Record<string, number> | null;
  created_at: string | null;
}

export async function getFilesByCourseId(courseId: string): Promise<UploadedCourseFile[]> {
  return request(`/content/files/by-course/${courseId}`);
}

export async function listIngestionJobs(courseId: string): Promise<IngestionJobSummary[]> {
  return request(`/content/jobs/${courseId}`);
}

// Preserve the existing misspelled export until all call sites are migrated.
export const getFilesByCoursId = getFilesByCourseId;

export async function getExamPrepPlan(
  courseId: string,
  daysUntilExam: number = 7,
  examTopic?: string,
): Promise<{
  course: string;
  topics_count: number;
  readiness: Record<string, number>;
  days_until_exam: number;
  plan: string;
}> {
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
): Promise<{ id: string; batch_id: string; version: number; replaced: boolean }> {
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

export interface AgentTask {
  id: string;
  user_id: string;
  course_id: string | null;
  task_type: string;
  status: string;
  title: string;
  summary: string | null;
  source: string;
  input_json: Record<string, unknown> | null;
  metadata_json: Record<string, unknown> | null;
  result_json: Record<string, unknown> | null;
  error_message: string | null;
  attempts: number;
  max_attempts: number;
  requires_approval: boolean;
  approved_at: string | null;
  started_at: string | null;
  cancel_requested_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

export async function listAgentTasks(courseId?: string): Promise<AgentTask[]> {
  const query = courseId ? `?course_id=${courseId}` : "";
  return request(`/tasks/${query}`);
}

export async function submitAgentTask(body: {
  task_type: string;
  title: string;
  course_id?: string;
  summary?: string;
  input_json?: Record<string, unknown>;
  metadata_json?: Record<string, unknown>;
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

export async function cancelAgentTask(taskId: string): Promise<AgentTask> {
  return request(`/tasks/${taskId}/cancel`, { method: "POST" });
}

export async function retryAgentTask(taskId: string): Promise<AgentTask> {
  return request(`/tasks/${taskId}/retry`, { method: "POST" });
}

export interface PreferenceSignal {
  id: string;
  dimension: string;
  value: string;
  signal_type: string;
  course_id: string | null;
  context: {
    evidence?: string;
    user_message?: string;
  } | null;
  created_at: string | null;
}

export async function listPreferenceSignals(courseId?: string): Promise<PreferenceSignal[]> {
  const query = courseId ? `?course_id=${courseId}` : "";
  return request(`/preferences/signals${query}`);
}
