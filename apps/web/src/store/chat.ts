/**
 * Chat store using Zustand.
 * Manages conversation messages, streaming state, and NL action dispatching.
 *
 * Phase 0-B: Handles [ACTION:...] markers from LLM responses (CopilotKit pattern).
 */

import { create } from "zustand";
import {
  getChatSessionMessages,
  listChatSessions,
  type PlanProgressEvent,
  streamChat,
  type ChatAction,
  type ChatHistoryMessage,
  type ChatMessageMetadata,
  type ChatSessionSummary,
  type ClarifyOption,
  type ImageAttachment,
} from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import { useWorkspaceStore } from "@/store/workspace";

/** TTL for cached chat session lists (per course). */
const SESSIONS_TTL_MS = 30_000; // 30 seconds

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  metadata?: ChatMessageMetadata | null;
  /** Images attached to user messages (base64-encoded). */
  images?: ImageAttachment[];
  /** URL for audio playback (voice mode TTS responses). */
  audioUrl?: string;
}

export interface SendMessageOptions {
  activeTab?: string;
  tabContext?: Record<string, unknown>;
  images?: ImageAttachment[];
  /** Internal flag: set automatically when the user interrupts an active stream. */
  interrupt?: boolean;
}

interface ChatState {
  activeCourseId: string | null;
  messagesByCourse: Record<string, ChatMessage[]>;
  sessionIds: Record<string, string>;
  sessionsByCourse: Record<string, ChatSessionSummary[]>;
  planProgressByCourse: Record<string, PlanProgressEvent | null>;
  messages: ChatMessage[];
  activePlan: PlanProgressEvent | null;
  isStreaming: boolean;
  isLoadingSessions: boolean;
  error: string | null;
  errorCategory: "rate_limit" | "auth_error" | "timeout" | "llm_unavailable" | "generic" | null;
  /** AbortController for cancelling active stream */
  _abortController: AbortController | null;
  abortStream: () => void;

  /** Active tool status from ReAct agent loop (null when no tool running). */
  toolStatus: { tool: string; status: "running" | "complete"; explanation?: string } | null;

  /** Active clarification options from the agent (null when none pending). */
  clarifyOptions: ClarifyOption | null;
  /** Send a clarification response by clicking an option button. */
  sendClarifyResponse: (courseId: string, key: string, value: string) => void;

  /** Callback for NL actions (layout changes and preference updates). Set by CoursePage. */
  onAction: ((action: ChatAction) => void) | null;
  setOnAction: (cb: (action: ChatAction) => void) => void;
  setCourseContext: (courseId: string) => void;
  loadSessions: (courseId: string, options?: { restoreLatest?: boolean }) => Promise<void>;
  loadSessionMessages: (courseId: string, sessionId: string) => Promise<void>;
  startNewSession: (courseId: string) => void;

  sendMessage: (courseId: string, content: string, options?: SendMessageOptions) => Promise<void>;
  clearMessages: (courseId?: string) => void;
}

// Use timestamp + random suffix to ensure unique IDs across page refreshes
let messageCounter = 0;
const sessionPrefix = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;

/**
 * Helper: compute the derived `messages` and `activePlan` fields from the
 * per-course maps.  Every `set()` call that touches `messagesByCourse` or
 * `planProgressByCourse` should spread the result of this helper so the
 * top-level `messages` / `activePlan` always stay in sync automatically.
 */
function deriveActive(
  state: Pick<ChatState, "messagesByCourse" | "planProgressByCourse" | "activeCourseId">,
) {
  const id = state.activeCourseId;
  return {
    messages: id ? state.messagesByCourse[id] ?? [] : [],
    activePlan: id ? state.planProgressByCourse[id] ?? null : null,
  };
}

export const useChatStore = create<ChatState>((set, get) => ({
  activeCourseId: null,
  messagesByCourse: {},
  sessionIds: {},
  sessionsByCourse: {},
  planProgressByCourse: {},
  messages: [],
  activePlan: null,
  isStreaming: false,
  isLoadingSessions: false,
  error: null,
  errorCategory: null,
  toolStatus: null,
  clarifyOptions: null,
  sendClarifyResponse: (courseId, key, value) => {
    // Don't clear clarifyOptions here — sendMessage already clears it.
    // Keeping it until sendMessage runs ensures retry is possible if the call fails.
    get().sendMessage(courseId, `[CLARIFY:${key}:${value}]`);
  },
  onAction: null,
  _abortController: null,
  abortStream: () => {
    const ctrl = get()._abortController;
    if (ctrl) {
      ctrl.abort();
      set({ _abortController: null, isStreaming: false, toolStatus: null });
    }
  },

  setOnAction: (cb) => set({ onAction: cb }),
  setCourseContext: (courseId) =>
    set((s) => {
      const next = { ...s, activeCourseId: courseId };
      return { activeCourseId: courseId, ...deriveActive(next), error: null };
    }),
  loadSessions: async (courseId, options) => {
    const cacheKey = `chat:sessions:${courseId}`;

    // Use cached session list when available and we don't need to restore.
    const cached = ttlCache.get<ChatSessionSummary[]>(cacheKey);
    if (cached && !options?.restoreLatest) {
      set((s) => ({
        sessionsByCourse: { ...s.sessionsByCourse, [courseId]: cached },
      }));
      return;
    }

    set({ isLoadingSessions: true, error: null });
    try {
      const sessions = await listChatSessions(courseId);
      ttlCache.set(cacheKey, sessions, SESSIONS_TTL_MS);
      set((s) => ({
        sessionsByCourse: { ...s.sessionsByCourse, [courseId]: sessions },
      }));

      const currentSessionId = get().sessionIds[courseId];
      const shouldRestoreLatest =
        options?.restoreLatest && !currentSessionId && sessions.length > 0 && (get().messagesByCourse[courseId]?.length ?? 0) === 0;

      if (shouldRestoreLatest) {
        await get().loadSessionMessages(courseId, sessions[0].id);
      }
    } catch (e) {
      set({ error: (e as Error).message });
    } finally {
      set({ isLoadingSessions: false });
    }
  },
  loadSessionMessages: async (courseId, sessionId) => {
    set({ isLoadingSessions: true, error: null });
    try {
      const pageSize = 200;
      const persistedMessages = [];
      let offset = 0;
      let totalMessages = Number.POSITIVE_INFINITY;

      while (offset < totalMessages) {
        const result = await getChatSessionMessages(sessionId, {
          limit: pageSize,
          offset,
        });
        totalMessages = result.session.message_count;
        persistedMessages.push(...result.messages);
        if (result.messages.length === 0) {
          break;
        }
        offset += result.messages.length;
      }

      const hydratedMessages: ChatMessage[] = persistedMessages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        timestamp: message.created_at ? new Date(message.created_at) : new Date(),
        metadata: message.metadata_json ?? null,
      }));
      set((s) => {
        const nextMBC = { ...s.messagesByCourse, [courseId]: hydratedMessages };
        const next = { ...s, activeCourseId: courseId, messagesByCourse: nextMBC };
        return {
          activeCourseId: courseId,
          messagesByCourse: nextMBC,
          sessionIds: { ...s.sessionIds, [courseId]: sessionId },
          ...deriveActive(next),
        };
      });
    } catch (e) {
      set({ error: (e as Error).message });
    } finally {
      set({ isLoadingSessions: false });
    }
  },
  startNewSession: (courseId) =>
    set((s) => {
      const nextMBC = { ...s.messagesByCourse, [courseId]: [] };
      const next = { ...s, activeCourseId: courseId, messagesByCourse: nextMBC };
      return {
        activeCourseId: courseId,
        messagesByCourse: nextMBC,
        sessionIds: Object.fromEntries(
          Object.entries(s.sessionIds).filter(([key]) => key !== courseId),
        ),
        ...deriveActive(next),
        error: null,
      };
    }),

  sendMessage: async (courseId, content, options?) => {
    if (get().activeCourseId !== courseId) {
      get().setCourseContext(courseId);
    }

    // ── Interrupt handling: if already streaming, abort current stream and
    //    finalize the partial assistant message before starting a new one. ──
    const wasInterrupted = get().isStreaming && get()._abortController;
    if (wasInterrupted) {
      const ctrl = get()._abortController;
      if (ctrl) ctrl.abort();
      set({ _abortController: null, isStreaming: false, toolStatus: null });
    }

    const userMsg: ChatMessage = {
      id: `msg-${sessionPrefix}-${++messageCounter}`,
      role: "user",
      content,
      timestamp: new Date(),
      images: options?.images,
    };

    const assistantMsg: ChatMessage = {
      id: `msg-${sessionPrefix}-${++messageCounter}`,
      role: "assistant",
      content: "",
      timestamp: new Date(),
    };

    const history: ChatHistoryMessage[] = [...(get().messagesByCourse[courseId] ?? []), userMsg]
      .slice(-10)
      .map((message) => ({
        role: message.role,
        content: message.content,
      }));

    set((s) => {
      const nextMBC = {
        ...s.messagesByCourse,
        [courseId]: [...(s.messagesByCourse[courseId] ?? []), userMsg, assistantMsg],
      };
      return {
        messagesByCourse: nextMBC,
        ...deriveActive({ ...s, messagesByCourse: nextMBC }),
        isStreaming: true,
        error: null,
        clarifyOptions: null,
      };
    });

    const controller = new AbortController();
    set({ _abortController: controller });
    try {
      for await (const event of streamChat({
        courseId,
        message: content,
        activeTab: options?.activeTab,
        tabContext: options?.tabContext,
        sessionId: get().sessionIds[courseId],
        history,
        signal: controller.signal,
        images: options?.images,
        interrupt: wasInterrupted ? true : undefined,
        learningMode: useWorkspaceStore.getState().spaceLayout?.mode,
      })) {
        if (event.type === "content") {
          set((s) => {
            const nextMBC = {
              ...s.messagesByCourse,
              [courseId]: (s.messagesByCourse[courseId] ?? []).map((m) =>
                m.id === assistantMsg.id ? { ...m, content: m.content + event.content } : m,
              ),
            };
            return { messagesByCourse: nextMBC, ...deriveActive({ ...s, messagesByCourse: nextMBC }) };
          });
        } else if (event.type === "action") {
          const { onAction } = get();
          if (onAction) {
            onAction(event.action);
          }
        } else if (event.type === "plan_step") {
          set((s) => ({
            activePlan: event.task,
            planProgressByCourse: {
              ...s.planProgressByCourse,
              [courseId]: event.task,
            },
          }));
        } else if (event.type === "tool_status") {
          set({ toolStatus: { tool: event.tool, status: event.status, explanation: event.explanation } });
          if (event.status === "complete") {
            setTimeout(() => set({ toolStatus: null }), 1500);
          }
        } else if (event.type === "tool_progress") {
          // Show write-tool progress as a tool_status with the progress message
          const pct = event.total > 0 ? ` (${event.step}/${event.total})` : "";
          set({ toolStatus: { tool: event.tool, status: "running", explanation: `${event.message}${pct}` } });
        } else if (event.type === "clarify") {
          set({ clarifyOptions: event.clarify });
        } else if (event.type === "replace") {
          set((s) => {
            const nextMBC = {
              ...s.messagesByCourse,
              [courseId]: (s.messagesByCourse[courseId] ?? []).map((m) =>
                m.id === assistantMsg.id ? { ...m, content: event.content } : m,
              ),
            };
            return { messagesByCourse: nextMBC, ...deriveActive({ ...s, messagesByCourse: nextMBC }) };
          });
        } else if (event.type === "done" && event.sessionId) {
          // Process any actions embedded in the envelope (e.g. from agent write tools).
          // These are not emitted as separate SSE "action" events, so handle them here.
          const doneActions = (event.metadata?.actions ?? []) as ChatAction[];
          const { onAction: doneOnAction } = get();
          if (doneOnAction) {
            for (const a of doneActions) {
              doneOnAction(a);
            }
          }

          // Apply layout simplification if cognitive load is high
          const simplification = event.metadata?.layout_simplification as
            | { should_simplify: boolean; blocks_to_hide: string[]; reason: string }
            | undefined;
          if (simplification?.should_simplify && simplification.blocks_to_hide.length > 0) {
            try {
              const { useWorkspaceStore } = await import("@/store/workspace");
              const ws = useWorkspaceStore.getState();
              const ops = simplification.blocks_to_hide
                .map((type: string) => {
                  const block = ws.spaceLayout.blocks.find((b) => b.type === type);
                  return block ? { action: "remove" as const, blockId: block.id } : null;
                })
                .filter(Boolean) as Array<{ action: "remove"; blockId: string }>;
              if (ops.length > 0) {
                ws.batchUpdateBlocks(ops);
              }
            } catch {
              // Best-effort — workspace store may not be available
            }
          }

          set((s) => {
            const nextMBC = {
              ...s.messagesByCourse,
              [courseId]: (s.messagesByCourse[courseId] ?? []).map((m) =>
                m.id === assistantMsg.id ? { ...m, metadata: event.metadata ?? m.metadata ?? null } : m,
              ),
            };
            return {
              messagesByCourse: nextMBC,
              ...deriveActive({ ...s, messagesByCourse: nextMBC }),
              sessionIds: { ...s.sessionIds, [courseId]: event.sessionId! },
            };
          });
        }
      }
      // Invalidate session cache so loadSessions fetches the fresh list
      // (a new session may have been created during the exchange).
      ttlCache.invalidate(`chat:sessions:${courseId}`);
      await get().loadSessions(courseId);
    } catch (e) {
      // Suppress abort errors caused by user interrupt — not a real failure.
      if (e instanceof DOMException && e.name === "AbortError") {
        return;
      }
      const msg = (e as Error).message || "";
      const category: ChatState["errorCategory"] =
        /rate.?limit|429/i.test(msg) ? "rate_limit" :
        /auth|401|403|api.?key|unauthorized/i.test(msg) ? "auth_error" :
        /timeout|timed?\s?out|abort/i.test(msg) ? "timeout" :
        /llm|model|provider|mock|circuit/i.test(msg) ? "llm_unavailable" :
        "generic";
      set({ error: msg, errorCategory: category });
    } finally {
      set({ isStreaming: false, toolStatus: null, _abortController: null });
    }
  },

  clearMessages: (courseId) =>
    set((s) => {
      const targetCourseId = courseId ?? s.activeCourseId;
      if (!targetCourseId) {
        return { messages: [], activePlan: null, error: null, sessionIds: {} };
      }

      const nextMBC = { ...s.messagesByCourse };
      delete nextMBC[targetCourseId];

      const nextSessionIds = { ...s.sessionIds };
      delete nextSessionIds[targetCourseId];

      const nextPPC = { ...s.planProgressByCourse };
      delete nextPPC[targetCourseId];

      const next = { ...s, messagesByCourse: nextMBC, planProgressByCourse: nextPPC };
      return {
        messagesByCourse: nextMBC,
        sessionIds: nextSessionIds,
        planProgressByCourse: nextPPC,
        ...deriveActive(next),
        error: null,
      };
    }),
}));
