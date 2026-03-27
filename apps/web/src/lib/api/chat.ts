import { API_BASE, buildSecureRequestInit, request, type JsonObject } from "./client";

// ── Chat types ──

interface ChatVerifierResult {
  status: "pass" | "repaired" | "failed";
  code: string;
  message: string;
}

export interface ChatVerifierDiagnostics {
  request_coverage?: number;
  evidence_coverage?: number;
  request_overlap_terms?: string[];
  evidence_overlap_terms?: string[];
}

interface ChatTaskLink {
  task_id: string;
  task_type: string;
  status: string;
}

type ChatActionType =
  // Block system actions
  | "data_updated"
  | "focus_topic"
  | "add_block"
  | "remove_block"
  | "reorder_blocks"
  | "resize_block"
  | "apply_template"
  | "agent_insight"
  | "set_learning_mode"
  | "suggest_mode";

export interface ChatAction {
  action: ChatActionType;
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

interface SessionMessagesResponse {
  session: ChatSessionSummary;
  messages: PersistedChatMessage[];
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
  evidence_summary?: string;
  matched_terms?: string[];
  matched_facets?: string[];
  section_hit_count?: number;
}

interface ChatEvidenceGroup {
  label?: string;
  titles?: string[];
  matched_terms?: string[];
  matched_facets?: string[];
  section_count?: number;
  summary?: string | null;
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
  content_evidence_groups?: ChatEvidenceGroup[];
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
  verifier_diagnostics?: ChatVerifierDiagnostics | null;
  task_link?: ChatTaskLink | null;
  /** True when backend used mock LLM fallback (no real API key configured). */
  is_mock?: boolean;
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
  | { type: "tool_progress"; tool: string; message: string; step: number; total: number }
  | { type: "clarify"; clarify: ClarifyOption }
  | { type: "block_update"; operations: BlockUpdateOp[]; cognitiveState: CognitiveState; explanation: string; interventionIds?: Record<string, string> }
  | { type: "done"; sessionId?: string; agent?: string; intent?: string; tokens?: number; metadata?: ChatMessageMetadata }
  | { type: "warning"; warningType: string; message: string };

export interface BlockUpdateOp {
  action: "add" | "remove" | "resize" | "reorder" | "update_config";
  block_type: string;
  reason: string;
  signal_source: string;
  urgency: number;
  config?: Record<string, unknown>;
  size?: string;
}

export interface CognitiveState {
  score: number;
  level: string;
  top_signals: Array<{ name: string; value: number }>;
}

export interface ClarifyOption {
  key: string;
  question: string;
  options: string[];
  agent: string;
  totalMissing: number;
}

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
  sessionId?: string;
  history?: ChatHistoryMessage[];
  signal?: AbortSignal;
  images?: ImageAttachment[];
  /** When true, indicates the user interrupted a previous streaming response. */
  interrupt?: boolean;
  /** Current learning mode from workspace store. */
  learningMode?: string;
  /** Current block types visible in the workspace. */
  blockTypes?: string[];
  /** Block types the user recently dismissed (last 7 days). */
  dismissedBlockTypes?: string[];
}

// ── Chat (SSE streaming) ──

export async function* streamChat(
  opts: ChatStreamOptions,
): AsyncGenerator<StreamEvent, void, unknown> {
  // Avoid the trailing slash here: FastAPI may emit a 307 redirect for `/chat/`,
  // which causes the browser to follow the backend origin directly and trip CORS.
  const res = await fetch(`${API_BASE}/chat`, {
    ...buildSecureRequestInit({
      method: "POST",
      includeJsonContentType: true,
      body: JSON.stringify({
        course_id: opts.courseId,
        message: opts.message,
        active_tab: opts.activeTab,
        tab_context: opts.tabContext,
        session_id: opts.sessionId,
        history: opts.history ?? [],
        images: opts.images ?? [],
        ...(opts.interrupt ? { interrupt: true } : {}),
        ...(opts.learningMode ? { learning_mode: opts.learningMode } : {}),
        ...(opts.blockTypes?.length ? { block_types: opts.blockTypes } : {}),
        ...(opts.dismissedBlockTypes?.length ? { dismissed_block_types: opts.dismissedBlockTypes } : {}),
      }),
      signal: opts.signal,
    }),
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
      } else if (resolvedEvent === "tool_progress") {
        yield {
          type: "tool_progress" as const,
          tool: data.tool as string,
          message: data.message as string,
          step: (data.step ?? 0) as number,
          total: (data.total ?? 0) as number,
        };
      } else if (resolvedEvent === "clarify") {
        if (data.key && data.question && Array.isArray(data.options)) {
          yield {
            type: "clarify",
            clarify: {
              key: data.key as string,
              question: data.question as string,
              options: data.options as string[],
              agent: (data.agent ?? "unknown") as string,
              totalMissing: (data.total_missing ?? 1) as number,
            },
          };
        }
      } else if (resolvedEvent === "block_update") {
        yield {
          type: "block_update",
          operations: (data.operations ?? []) as BlockUpdateOp[],
          cognitiveState: (data.cognitive_state ?? { score: 0, level: "low", top_signals: [] }) as CognitiveState,
          explanation: (data.explanation ?? "") as string,
          interventionIds: (data.intervention_ids ?? undefined) as Record<string, string> | undefined,
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
            verifier_diagnostics: data.verifier_diagnostics,
            task_link: data.task_link,
            reflection: data.reflection,
            is_mock: data.is_mock,
          },
        };
      } else if (resolvedEvent === "warning") {
        yield {
          type: "warning" as const,
          warningType: (data.type ?? "unknown") as string,
          message: (data.message ?? "") as string,
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

export async function getChatGreeting(courseId: string): Promise<{
  greeting: string;
  course_name: string;
  suggested_actions?: Array<{ action: string; value: string; extra?: string }>;
  degraded?: string[];
}> {
  return request(`/chat/greeting/${courseId}`);
}

export async function listChatSessions(courseId: string): Promise<ChatSessionSummary[]> {
  return request(`/chat/courses/${courseId}/sessions`);
}

export async function getChatSessionMessages(
  sessionId: string,
  options?: { limit?: number; offset?: number },
): Promise<SessionMessagesResponse> {
  const params = new URLSearchParams();
  if (options?.limit) params.set("limit", String(options.limit));
  if (options?.offset) params.set("offset", String(options.offset));
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return request(`/chat/sessions/${sessionId}/messages${suffix}`);
}
