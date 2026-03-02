/**
 * API client for OpenTutor backend.
 *
 * Simple fetch-based client. Phase 1 may upgrade to tRPC or orpc.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

type JsonObject = Record<string, unknown>;
type NullableDateTime = string | null;

interface VersionedBatch {
  batch_id: string;
  version: number;
  replaced: boolean;
}

interface SavedGeneratedAsset extends VersionedBatch {
  id: string;
}

interface ContentMutationResult {
  nodes_created: number;
}

interface ChatVerifierResult {
  status: "pass" | "repaired" | "failed";
  code: string;
  message: string;
}

interface ChatTaskLink {
  task_id: string;
  task_type: string;
  status: string;
}

interface SessionMessagesResponse {
  session: ChatSessionSummary;
  messages: PersistedChatMessage[];
}

interface LearningProfileSummary {
  strength_areas: string[];
  weak_areas: string[];
  recurring_errors: string[];
  inferred_habits: string[];
}

interface WorkspaceTabPlacement {
  type: string;
  position: number;
}

interface SceneInitAction {
  type: string;
  action: string;
  message: string;
}

interface SceneSwitchExplanationSummary {
  workflow?: string;
  recommended_tabs?: string[];
  reason?: string;
}

interface WrongAnswerDetail {
  category?: string;
  confidence?: number;
  evidence?: string;
  related_concept?: string;
  diagnosis?: string;
  original_correct?: boolean;
  clean_correct?: boolean;
  diagnostic_problem_id?: string;
}

interface RetryWrongAnswerResult {
  is_correct: boolean;
  correct_answer: string | null;
  explanation: string | null;
}

interface DerivedQuestionResult {
  problem_id: string;
  question: string;
  question_type: string;
  options: Record<string, string> | null;
  correct_answer: string | null;
  explanation: string | null;
}

interface WrongAnswerDiagnosisResult {
  diagnosis?: string;
  original_correct?: boolean;
  clean_correct?: boolean | null;
  interpretation?: string;
  status?: string;
  diagnostic_problem_id?: string;
  message?: string;
}

interface WrongAnswerStats {
  total: number;
  mastered: number;
  unmastered: number;
  by_category: Record<string, number>;
  by_diagnosis: Record<string, number>;
}

interface GeneratedQuizSaveResult extends VersionedBatch {
  saved: number;
  problem_ids: string[];
}

interface LearningOverviewCourseSummary {
  course_id: string;
  course_name: string;
  average_mastery: number;
  study_minutes: number;
  wrong_answers: number;
  diagnosed_count: number;
  gap_types: Record<string, number>;
}

interface DateRange {
  start: string;
  end: string;
}

interface WeeklyActivitySnapshot {
  study_minutes: number;
  active_days: number;
  quiz_total: number;
  quiz_correct: number;
  accuracy: number;
}

interface WeeklyActivityDelta {
  study_minutes: number;
  accuracy: number;
  quiz_total: number;
}

interface FlashcardFsrsState {
  difficulty: number;
  stability: number;
  reps: number;
  state: string;
  due: string | null;
  last_review?: string | null;
}

interface FlashcardGenerationResult {
  cards: Flashcard[];
  count: number;
}

interface FlashcardReviewResult {
  card: Flashcard;
  next_review: string | null;
}

interface DueFlashcardsResult {
  cards: Flashcard[];
  due_count: number;
  total_batches: number;
}

interface KnowledgeGraphData {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
}

interface WrongAnswerReviewResult {
  review: string;
  wrong_answer_count: number;
  wrong_answer_ids: string[];
}

interface ExamPrepPlan {
  course: string;
  topics_count: number;
  readiness: Record<string, number>;
  days_until_exam: number;
  plan: string;
}

interface PreferenceSignalContext {
  evidence?: string;
  user_message?: string;
}

interface QuizExtractionResult {
  problems_created: number;
}

interface GeneratedBatchSummaryBase {
  batch_id: string;
  title: string;
  current_version: number;
  is_active: boolean;
  updated_at: NullableDateTime;
}

interface LlmRuntimeUpdateRequest {
  provider?: string;
  model?: string;
  llm_required?: boolean;
  provider_keys?: Record<string, string>;
  base_url?: string;
}

interface LlmRuntimeConnectionTestRequest {
  provider: string;
  model?: string;
  api_key?: string;
}

interface PreferenceUpdateRequest {
  value?: string;
  scope?: string;
  source?: string;
  scene_type?: string | null;
}

interface MemoryUpdateRequest {
  summary?: string;
  category?: string | null;
}

interface AgentTaskSubmitRequest {
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
}

interface StudyGoalCreateRequest {
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

interface StudyGoalUpdateRequest {
  title: string;
  objective: string;
  success_metric: string;
  current_milestone: string;
  next_action: string;
  status: string;
  confidence: string;
  target_date: string | null;
  metadata_json: JsonObject | null;
}

interface PushSubscriptionRequest {
  endpoint: string;
  p256dh_key: string;
  auth_key: string;
  user_agent: string;
}

interface PushUnsubscribeRequest {
  endpoint: string;
}

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

export interface CourseWorkspaceFeatures {
  notes: boolean;
  practice: boolean;
  wrong_answer: boolean;
  study_plan: boolean;
  free_qa: boolean;
}

export interface CourseAutoScrapeSettings {
  enabled: boolean;
  interval_hours: number;
}

export interface CourseMetadata {
  workspace_features?: Partial<CourseWorkspaceFeatures> | null;
  auto_scrape?: CourseAutoScrapeSettings | null;
}

export interface Course {
  id: string;
  name: string;
  description: string | null;
  metadata?: CourseMetadata | null;
  created_at: string;
  updated_at?: string | null;
  file_count?: number;
  content_node_count?: number;
  active_goal_count?: number;
  pending_task_count?: number;
  pending_approval_count?: number;
  last_agent_activity_at?: string | null;
  last_scene_id?: string | null;
}

export interface CourseOverviewCard extends Course {
  updated_at: string | null;
  file_count: number;
  content_node_count: number;
  active_goal_count: number;
  pending_task_count: number;
  pending_approval_count: number;
  last_agent_activity_at: string | null;
  last_scene_id: string | null;
}

export interface HealthStatus {
  status: string;
  version: string;
  database: string;
  schema?: "ready" | "missing" | "unknown" | string;
  migration_required?: boolean;
  migration_status?: string;
  alembic_version_present?: boolean;
  migration_current_revisions?: string[];
  migration_expected_revisions?: string[];
  llm_providers: string[];
  llm_primary: string | null;
  llm_required: boolean;
  llm_available: boolean;
  llm_status: "configuration_required" | "mock_fallback" | "degraded" | "ready";
  llm_provider_health: Record<string, boolean>;
  deployment_mode: "single_user" | "multi_user" | string;
  code_sandbox_backend: string;
  code_sandbox_runtime: string;
  code_sandbox_runtime_available: boolean;
}

interface LlmRuntimeProviderStatus {
  provider: string;
  has_key: boolean;
  masked_key: string | null;
  requires_key?: boolean;
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

export async function listCourseOverview(): Promise<CourseOverviewCard[]> {
  return request("/courses/overview");
}

export async function getHealthStatus(): Promise<HealthStatus> {
  return request("/health");
}

export async function getLlmRuntimeConfig(): Promise<LlmRuntimeConfig> {
  return request("/preferences/runtime/llm");
}

export async function updateLlmRuntimeConfig(body: LlmRuntimeUpdateRequest): Promise<LlmRuntimeConfig> {
  return request("/preferences/runtime/llm", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function testLlmRuntimeConnection(body: LlmRuntimeConnectionTestRequest): Promise<LlmConnectionTestResult> {
  return request("/preferences/runtime/llm/test", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface OllamaModel {
  name: string;
  size: number;
  modified_at: string;
}

export async function getOllamaModels(baseUrl?: string): Promise<OllamaModel[]> {
  const params = baseUrl ? `?base_url=${encodeURIComponent(baseUrl)}` : "";
  return request(`/preferences/runtime/ollama/models${params}`);
}

export async function createCourse(
  name: string,
  description?: string,
  metadata?: CourseMetadata,
): Promise<Course> {
  return request("/courses/", {
    method: "POST",
    body: JSON.stringify({ name, description, metadata }),
  });
}

export async function updateCourse(
  courseId: string,
  payload: {
    name?: string;
    description?: string;
    metadata?: CourseMetadata;
  },
): Promise<Course> {
  return request(`/courses/${courseId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
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

interface RestructuredNotes {
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
): Promise<SavedGeneratedAsset> {
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

export async function uploadFile(courseId: string, file: File): Promise<ContentMutationResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("course_id", courseId);

  const res = await fetch(`${API_BASE}/content/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || error.message || "Upload failed");
  }
  return res.json();
}

export async function scrapeUrl(courseId: string, url: string): Promise<ContentMutationResult> {
  const form = new FormData();
  form.append("url", url);
  form.append("course_id", courseId);

  const res = await fetch(`${API_BASE}/content/url`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || error.message || "Scrape failed");
  }
  return res.json();
}

export interface ScrapeSource {
  id: string;
  url: string;
  label: string | null;
  course_id: string;
  source_type: string;
  requires_auth: boolean;
  auth_domain: string | null;
  session_name: string | null;
  enabled: boolean;
  interval_hours: number;
  last_scraped_at: string | null;
  last_status: string | null;
  last_content_hash: string | null;
  consecutive_failures: number;
  created_at: string;
}

export async function createScrapeSource(body: {
  course_id: string;
  url: string;
  label?: string;
  source_type?: "generic" | "canvas";
  requires_auth?: boolean;
  auth_domain?: string;
  session_name?: string;
  interval_hours?: number;
}): Promise<ScrapeSource> {
  return request("/scrape/sources", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ── Canvas / Auth Sessions ──

export interface AuthSessionSummary {
  id: string;
  domain: string;
  session_name: string;
  auth_type: string;
  is_valid: boolean;
  last_validated_at: string | null;
}

export async function listAuthSessions(): Promise<AuthSessionSummary[]> {
  return request("/scrape/auth/sessions");
}

export async function canvasBrowserLogin(
  canvasUrl: string,
): Promise<{ status: string; message: string }> {
  return request("/canvas/browser-login", {
    method: "POST",
    body: JSON.stringify({ canvas_url: canvasUrl, timeout_seconds: 300 }),
  });
}

export async function validateAuthSession(
  sessionName: string,
): Promise<{ session_name: string; is_valid: boolean }> {
  return request(`/scrape/auth/validate/${encodeURIComponent(sessionName)}`, {
    method: "POST",
  });
}

// ── Chat (SSE streaming) ──

type ChatActionType =
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

interface PersistedChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  metadata_json?: ChatMessageMetadata | null;
  created_at: string | null;
}

interface ChatSceneExplanation {
  scene?: string;
  mode?: string;
  matched_text?: string | null;
  current_scene?: string;
  target_scene?: string;
  matched_keywords?: string[];
  reason?: string;
  expected_benefit?: string;
  reversible_action?: string;
  layout_policy?: string;
  reasoning_policy?: string;
  workflow_policy?: string;
}

interface ChatPreferenceDetail {
  dimension: string;
  value: string;
  source: string;
}

interface ChatContentReference {
  title?: string;
  source_type?: string;
  preview?: string;
}

export interface ChatProvenance {
  scene?: string;
  workflow?: string;
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
  generated?: boolean;
  user_input?: boolean;
  source_labels?: string[];
  scheduler_trigger?: string;
}

export interface ChatMessageMetadata {
  agent?: string;
  intent?: string;
  tokens?: number;
  actions?: ChatAction[];
  reflection?: JsonObject | null;
  provenance?: ChatProvenance | null;
  verifier?: ChatVerifierResult | null;
  task_link?: ChatTaskLink | null;
}

interface PlanStepProgress {
  step_index: number;
  step_type: string;
  title: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped" | string;
  depends_on?: number[];
  summary?: string | null;
  agent?: string | null;
}

export interface PlanProgressEvent {
  taskId: string;
  steps: PlanStepProgress[];
  message?: string;
}

type StreamEvent =
  | { type: "content"; content: string }
  | { type: "action"; action: ChatAction }
  | { type: "status"; phase: string; intent?: string; confidence?: number; agent?: string }
  | { type: "plan_step"; task: PlanProgressEvent }
  | { type: "replace"; content: string }
  | { type: "tool_status"; status: "running" | "complete"; tool: string; explanation?: string }
  | { type: "done"; sessionId?: string; agent?: string; intent?: string; tokens?: number; metadata?: ChatMessageMetadata };

export interface ImageAttachment {
  data: string;       // base64-encoded
  media_type: string; // "image/png" | "image/jpeg" | "image/webp"
  filename?: string;
}

interface ChatStreamOptions {
  courseId: string;
  message: string;
  activeTab?: string;
  tabContext?: Record<string, unknown>;
  scene?: string;
  sessionId?: string;
  history?: ChatHistoryMessage[];
  signal?: AbortSignal;
  images?: ImageAttachment[];
  /** When true, indicates the user interrupted a previous streaming response. */
  interrupt?: boolean;
}

export async function* streamChat(
  opts: ChatStreamOptions,
): AsyncGenerator<StreamEvent, void, unknown> {
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
      ...(opts.interrupt ? { interrupt: true } : {}),
    }),
    signal: opts.signal,
  });

  if (!res.ok || !res.body) {
    if (res.status === 429) {
      const retryAfter = res.headers.get("Retry-After");
      const error = await res.json().catch(() => ({}));
      const seconds = retryAfter || error.retry_after || "a few";
      throw new Error(`Rate limit exceeded. Please wait ${seconds} seconds before trying again.`);
    }
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
      } else if (resolvedEvent === "plan_step") {
        yield {
          type: "plan_step",
          task: {
            taskId: data.task_id,
            steps: data.steps ?? [],
            message: data.message,
          },
        };
      } else if (resolvedEvent === "replace" && data.content) {
        yield { type: "replace", content: data.content };
      } else if (resolvedEvent === "tool_status") {
        yield {
          type: "tool_status",
          status: data.status,
          tool: data.tool,
          explanation: data.explanation,
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
            verifier: data.verifier,
            task_link: data.task_link,
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
): Promise<SessionMessagesResponse> {
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
  dismissed_at?: string | null;
  dismissal_reason?: string | null;
  updated_at: string;
}

export interface MemoryProfileItem {
  id: string;
  summary: string;
  memory_type: string;
  category: string | null;
  importance: number;
  access_count: number;
  source_message: string | null;
  metadata_json: JsonObject | null;
  created_at: NullableDateTime;
  updated_at: NullableDateTime;
  dismissed_at?: string | null;
  dismissal_reason?: string | null;
}

export interface LearningProfile {
  preferences: Preference[];
  dismissed_preferences: Preference[];
  signals: PreferenceSignal[];
  dismissed_signals: PreferenceSignal[];
  memories: MemoryProfileItem[];
  dismissed_memories: MemoryProfileItem[];
  summary: LearningProfileSummary;
}

export async function getLearningProfile(courseId?: string): Promise<LearningProfile> {
  const params = courseId ? `?course_id=${courseId}` : "";
  return request(`/preferences/profile${params}`);
}

export async function listPreferences(courseId?: string): Promise<Preference[]> {
  const params = courseId ? `?course_id=${encodeURIComponent(courseId)}` : "";
  return request(`/preferences/${params}`);
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

export async function updatePreferenceItem(
  preferenceId: string,
  body: PreferenceUpdateRequest,
): Promise<Preference> {
  return request(`/preferences/${preferenceId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function dismissPreferenceItem(preferenceId: string, reason?: string): Promise<Preference> {
  return request(`/preferences/${preferenceId}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export async function restorePreferenceItem(preferenceId: string): Promise<Preference> {
  return request(`/preferences/${preferenceId}/restore`, {
    method: "POST",
  });
}

export async function dismissPreferenceSignal(signalId: string, reason?: string): Promise<PreferenceSignal> {
  return request(`/preferences/signals/${signalId}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export async function restorePreferenceSignal(signalId: string): Promise<PreferenceSignal> {
  return request(`/preferences/signals/${signalId}/restore`, {
    method: "POST",
  });
}

export async function updateMemoryItem(
  memoryId: string,
  body: MemoryUpdateRequest,
): Promise<MemoryProfileItem> {
  return request(`/preferences/memories/${memoryId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function dismissMemoryItem(memoryId: string, reason?: string): Promise<MemoryProfileItem> {
  return request(`/preferences/memories/${memoryId}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export async function restoreMemoryItem(memoryId: string): Promise<MemoryProfileItem> {
  return request(`/preferences/memories/${memoryId}/restore`, {
    method: "POST",
  });
}

// ── Scenes ──

export interface SceneConfig {
  scene_id: string;
  display_name: string;
  icon: string | null;
  tab_preset: WorkspaceTabPlacement[];
  workflow: string;
  ai_behavior: JsonObject;
  preferences: Record<string, string> | null;
  layout_policy?: string;
  reasoning_policy?: string;
  workflow_policy?: string;
}

interface ActiveSceneResult {
  scene_id: string;
  config: SceneConfig;
  snapshot: JsonObject | null;
}

export interface SwitchResult {
  switched: boolean;
  scene_id: string;
  from_scene?: string;
  config: SceneConfig;
  tab_layout?: WorkspaceTabPlacement[];
  init_actions: SceneInitAction[];
  message?: string;
  explanation?: SceneSwitchExplanationSummary;
}

export interface SceneRecommendation {
  scene_id: string;
  confidence: number;
  switch_recommended: boolean;
  reason: string;
  scores: Record<string, number>;
  features: JsonObject;
  expected_benefit?: string;
  reversible_action?: string;
  layout_policy?: string;
  reasoning_policy?: string;
  workflow_policy?: string;
}

export async function listScenes(): Promise<SceneConfig[]> {
  return request("/scenes/");
}

export async function getActiveScene(courseId: string): Promise<ActiveSceneResult> {
  return request(`/scenes/${courseId}/active`);
}

export async function recommendScene(courseId: string, activeTab?: string, message?: string): Promise<SceneRecommendation> {
  const params = new URLSearchParams();
  if (message) params.set("message", message);
  if (activeTab) params.set("active_tab", activeTab);
  const query = params.toString();
  return request(`/scenes/${courseId}/recommend${query ? `?${query}` : ""}`);
}

export async function switchScene(
  courseId: string,
  sceneId: string,
  currentUiState?: JsonObject,
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
  error_detail: WrongAnswerDetail | null;
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
  return request<RetryWrongAnswerResult>(
    `/wrong-answers/${id}/retry`,
    { method: "POST", body: JSON.stringify({ user_answer: userAnswer }) },
  );
}

export async function deriveQuestion(id: string) {
  return request<DerivedQuestionResult>(
    `/wrong-answers/${id}/derive`,
    { method: "POST" },
  );
}

export async function diagnoseWrongAnswer(id: string): Promise<WrongAnswerDiagnosisResult> {
  return request(`/wrong-answers/${id}/diagnose`, {
    method: "POST",
  });
}

export async function getWrongAnswerStats(courseId: string): Promise<WrongAnswerStats> {
  return request(`/wrong-answers/${courseId}/stats`);
}

export interface QuizProblem {
  id: string;
  question_type: string;
  question: string;
  options: Record<string, string> | null;
  order_index: number;
}

interface GeneratedQuizDraft {
  question_type: string;
  question: string;
  options: Record<string, string> | null;
  correct_answer?: string | null;
  explanation?: string | null;
  difficulty_layer?: number | null;
  problem_metadata?: Record<string, unknown> | null;
}

export interface GeneratedQuizBatchSummary {
  batch_id: GeneratedBatchSummaryBase["batch_id"];
  title: GeneratedBatchSummaryBase["title"];
  current_version: GeneratedBatchSummaryBase["current_version"];
  problem_count: number;
  is_active: GeneratedBatchSummaryBase["is_active"];
  updated_at: GeneratedBatchSummaryBase["updated_at"];
}

export interface GeneratedAssetBatchSummary extends GeneratedBatchSummaryBase {
  asset_count: number;
  preview: JsonObject;
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
  const normalizeDraftPayload = (payload: unknown): GeneratedQuizDraft[] => {
    if (Array.isArray(payload)) {
      return payload.filter(
        (item): item is GeneratedQuizDraft =>
          Boolean(item) && typeof item === "object" && typeof item.question === "string" && typeof item.question_type === "string",
      );
    }
    if (
      payload &&
      typeof payload === "object" &&
      typeof (payload as GeneratedQuizDraft).question === "string" &&
      typeof (payload as GeneratedQuizDraft).question_type === "string"
    ) {
      return [payload as GeneratedQuizDraft];
    }
    return [];
  };

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
      const drafts = normalizeDraftPayload(parsed);
      if (drafts.length > 0) {
        return drafts;
      }
    } catch {
      // Try next candidate.
    }
  }
  return [];
}

export async function extractQuiz(courseId: string): Promise<QuizExtractionResult> {
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
): Promise<GeneratedQuizSaveResult> {
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
  course_summaries: LearningOverviewCourseSummary[];
}

export async function getCourseProgress(courseId: string): Promise<CourseProgress> {
  return request(`/progress/courses/${courseId}`);
}

export async function getLearningOverview(): Promise<LearningOverview> {
  return request("/progress/overview");
}

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

export interface WeeklyReport {
  period: DateRange;
  this_week: WeeklyActivitySnapshot;
  last_week: WeeklyActivitySnapshot;
  deltas: WeeklyActivityDelta;
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

export interface Flashcard {
  id: string;
  front: string;
  back: string;
  difficulty: string;
  fsrs: FlashcardFsrsState;
}

export async function generateFlashcards(
  courseId: string,
  count: number = 5,
): Promise<FlashcardGenerationResult> {
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
): Promise<SavedGeneratedAsset> {
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
): Promise<FlashcardReviewResult> {
  return request("/flashcards/review", {
    method: "POST",
    body: JSON.stringify({ card, rating }),
  });
}

export async function getDueFlashcards(
  courseId: string,
): Promise<DueFlashcardsResult> {
  return request(`/flashcards/due/${courseId}`);
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
): Promise<KnowledgeGraphData> {
  return request(`/progress/courses/${courseId}/knowledge-graph`);
}

export async function getWrongAnswerReview(courseId: string): Promise<WrongAnswerReviewResult> {
  return request(`/workflows/wrong-answer-review?course_id=${courseId}`);
}

export function getFileUrl(jobId: string): string {
  return `${API_BASE}/content/files/${jobId}`;
}

interface UploadedCourseFile {
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
  phase_label: string | null;
  progress_percent: number;
  nodes_created: number;
  embedding_status: "pending" | "running" | "completed" | "failed";
  error_message: string | null;
  dispatched_to: Record<string, number> | null;
  created_at: NullableDateTime;
  updated_at: NullableDateTime;
}

export async function getFilesByCourseId(courseId: string): Promise<UploadedCourseFile[]> {
  return request(`/content/files/by-course/${courseId}`);
}

export async function listIngestionJobs(courseId: string): Promise<IngestionJobSummary[]> {
  return request(`/content/jobs/${courseId}`);
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
}

export interface AgentTaskReview {
  status: string;
  outcome: string;
  blockers: string[];
  next_recommended_action: string | null;
  follow_up: AgentTaskReviewFollowUp;
  goal_update: AgentTaskReviewGoalUpdate | null;
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

export async function submitAgentTask(body: AgentTaskSubmitRequest): Promise<AgentTask> {
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

export async function cancelAgentTask(taskId: string): Promise<AgentTask> {
  return request(`/tasks/${taskId}/cancel`, { method: "POST" });
}

export async function resumeAgentTask(taskId: string): Promise<AgentTask> {
  return request(`/tasks/${taskId}/resume`, { method: "POST" });
}

export async function retryAgentTask(taskId: string): Promise<AgentTask> {
  return request(`/tasks/${taskId}/retry`, { method: "POST" });
}

export async function queueTaskFollowUp(taskId: string): Promise<AgentTask> {
  return request(`/tasks/${taskId}/follow-up`, { method: "POST" });
}

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

export async function queueNextAction(courseId: string): Promise<AgentTask> {
  return request(`/goals/${courseId}/next-action/queue`, {
    method: "POST",
  });
}

export async function createStudyGoal(body: StudyGoalCreateRequest): Promise<StudyGoal> {
  return request("/goals/", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateStudyGoal(goalId: string, body: Partial<StudyGoalUpdateRequest>): Promise<StudyGoal> {
  return request(`/goals/${goalId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export interface PreferenceSignal {
  id: string;
  dimension: string;
  value: string;
  signal_type: string;
  course_id: string | null;
  context: PreferenceSignalContext | null;
  created_at: NullableDateTime;
  dismissed_at?: string | null;
  dismissal_reason?: string | null;
}

export async function listPreferenceSignals(courseId?: string): Promise<PreferenceSignal[]> {
  const query = courseId ? `?course_id=${courseId}` : "";
  return request(`/preferences/signals${query}`);
}

// ── Push Notifications ──

interface VapidKeyResponse {
  public_key: string;
}

export async function getVapidKey(): Promise<VapidKeyResponse> {
  return request("/notifications/push/vapid-key");
}

export async function subscribePush(body: PushSubscriptionRequest): Promise<void> {
  return request("/notifications/push/subscribe", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function unsubscribePush(body: PushUnsubscribeRequest): Promise<void> {
  return request("/notifications/push/unsubscribe", {
    method: "DELETE",
    body: JSON.stringify(body),
  });
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

// ── NL Preference Parsing ──

interface NLPreferenceResult {
  dimension: string | null;
  value: string | null;
  label: string | null;
}

export async function parseNLPreference(text: string): Promise<NLPreferenceResult> {
  return request("/preferences/parse-nl", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}
