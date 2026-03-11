/** Chat store — conversation messages, streaming state, NL action dispatching. */
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
import { applyBlockDecisions, categorizeError } from "./chat-stream";
import { getDismissHistory } from "./workspace-blocks";

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
}

export interface SendMessageOptions {
  activeTab?: string;
  tabContext?: Record<string, unknown>;
  images?: ImageAttachment[];
  /** Internal flag: set automatically when the user interrupts an active stream. */
  interrupt?: boolean;
}

interface ChatActionHandlerEntry {
  handler: (action: ChatAction) => void;
  isFallback: boolean;
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
  /** True when the backend is using the mock LLM fallback (no real API key configured). */
  isMockLlm: boolean;
  /** AbortController for cancelling active stream */
  _abortController: AbortController | null;
  /** Timer ID for the tool_status "complete" auto-clear timeout. */
  _toolStatusTimer: ReturnType<typeof setTimeout> | null;
  abortStream: () => void;

  /** Active tool status from ReAct agent loop (null when no tool running). */
  toolStatus: { tool: string; status: "running" | "complete"; explanation?: string } | null;

  /** Active clarification options from the agent (null when none pending). */
  clarifyOptions: ClarifyOption | null;
  /** Send a clarification response by clicking an option button. */
  sendClarifyResponse: (courseId: string, key: string, value: string) => void;

  /** Registered NL action handlers from page-level hooks/components. */
  actionHandlers: Record<string, ChatActionHandlerEntry>;
  actionHandlerOrder: string[];
  registerOnAction: (cb: (action: ChatAction) => void) => () => void;
  registerFallbackOnAction: (cb: (action: ChatAction) => void) => () => void;
  dispatchAction: (action: ChatAction) => void;
  setCourseContext: (courseId: string) => void;
  loadSessions: (courseId: string, options?: { restoreLatest?: boolean }) => Promise<void>;
  loadSessionMessages: (courseId: string, sessionId: string) => Promise<void>;
  startNewSession: (courseId: string) => void;

  sendMessage: (courseId: string, content: string, options?: SendMessageOptions) => Promise<void>;
  clearMessages: (courseId?: string) => void;
}

let messageCounter = 0;
const sessionPrefix = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
let actionHandlerCounter = 0;

/** Compute derived `messages`/`activePlan` from per-course maps. */
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
  isMockLlm: false,
  toolStatus: null,
  clarifyOptions: null,
  sendClarifyResponse: (courseId, key, value) => {
    get().sendMessage(courseId, JSON.stringify({ type: "clarify", key, value }));
  },
  actionHandlers: {},
  actionHandlerOrder: [],
  _abortController: null,
  _toolStatusTimer: null,
  abortStream: () => {
    const ctrl = get()._abortController;
    if (ctrl) {
      ctrl.abort();
      const t = get()._toolStatusTimer;
      if (t) clearTimeout(t);
      set({ _abortController: null, isStreaming: false, toolStatus: null, _toolStatusTimer: null });
    }
  },

  registerOnAction: (cb) => {
    const handlerId = `action-${++actionHandlerCounter}`;
    set((s) => ({
      actionHandlers: {
        ...s.actionHandlers,
        [handlerId]: { handler: cb, isFallback: false },
      },
      actionHandlerOrder: [...s.actionHandlerOrder, handlerId],
    }));
    return () =>
      set((s) => {
        if (!s.actionHandlers[handlerId]) return {};
        const nextHandlers = { ...s.actionHandlers };
        delete nextHandlers[handlerId];
        return {
          actionHandlers: nextHandlers,
          actionHandlerOrder: s.actionHandlerOrder.filter((id) => id !== handlerId),
        };
      });
  },
  registerFallbackOnAction: (cb) => {
    const handlerId = `action-${++actionHandlerCounter}`;
    set((s) => ({
      actionHandlers: {
        ...s.actionHandlers,
        [handlerId]: { handler: cb, isFallback: true },
      },
      actionHandlerOrder: [...s.actionHandlerOrder, handlerId],
    }));
    return () =>
      set((s) => {
        if (!s.actionHandlers[handlerId]) return {};
        const nextHandlers = { ...s.actionHandlers };
        delete nextHandlers[handlerId];
        return {
          actionHandlers: nextHandlers,
          actionHandlerOrder: s.actionHandlerOrder.filter((id) => id !== handlerId),
        };
      });
  },
  dispatchAction: (action) => {
    const { actionHandlers, actionHandlerOrder } = get();
    const primaryHandlers: Array<(event: ChatAction) => void> = [];
    const fallbackHandlers: Array<(event: ChatAction) => void> = [];

    for (const handlerId of actionHandlerOrder) {
      const entry = actionHandlers[handlerId];
      if (!entry) continue;
      if (entry.isFallback) {
        fallbackHandlers.push(entry.handler);
      } else {
        primaryHandlers.push(entry.handler);
      }
    }

    const handlersToRun = primaryHandlers.length > 0 ? primaryHandlers : fallbackHandlers;
    for (const handler of handlersToRun) {
      handler(action);
    }
  },
  setCourseContext: (courseId) =>
    set((s) => {
      const next = { ...s, activeCourseId: courseId };
      return { activeCourseId: courseId, ...deriveActive(next), error: null, isMockLlm: false };
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
    //    finalize the partial assistant message before starting a new one.
    //    Capture controller in a single read to avoid TOCTOU race. ──
    const prevCtrl = get()._abortController;
    const wasInterrupted = get().isStreaming && prevCtrl != null;
    if (wasInterrupted) {
      prevCtrl.abort();
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

    // Abort any stale controller that may have been left over (defensive)
    const prev = get()._abortController;
    if (prev) prev.abort();
    const controller = new AbortController();
    set({ _abortController: controller });
    try {
      const wsState = useWorkspaceStore.getState();
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
        learningMode: wsState.spaceLayout?.mode,
        blockTypes: wsState.spaceLayout?.blocks?.map((b) => b.type),
        dismissedBlockTypes: getDismissHistory(courseId),
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
          get().dispatchAction(event.action);
        } else if (event.type === "plan_step") {
          set((s) => ({
            activePlan: event.task,
            planProgressByCourse: {
              ...s.planProgressByCourse,
              [courseId]: event.task,
            },
          }));
        } else if (event.type === "tool_status") {
          // Clear any pending auto-clear timer before updating tool status
          const prevTimer = get()._toolStatusTimer;
          if (prevTimer) clearTimeout(prevTimer);
          set({ toolStatus: { tool: event.tool, status: event.status, explanation: event.explanation }, _toolStatusTimer: null });
          if (event.status === "complete") {
            const timer = setTimeout(() => set({ toolStatus: null, _toolStatusTimer: null }), 1500);
            set({ _toolStatusTimer: timer });
          }
        } else if (event.type === "tool_progress") {
          // Show write-tool progress as a tool_status with the progress message
          const pct = event.total > 0 ? ` (${event.step}/${event.total})` : "";
          set({ toolStatus: { tool: event.tool, status: "running", explanation: `${event.message}${pct}` } });
        } else if (event.type === "clarify") {
          set({ clarifyOptions: event.clarify });
        } else if (event.type === "block_update") {
          await applyBlockDecisions(event);
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
        } else if (event.type === "warning") {
          // Show SSE warnings (e.g. persistence failure) as toast
          const { toast } = await import("sonner");
          toast.warning(event.message);
        } else if (event.type === "done" && event.sessionId) {
          // Detect mock LLM usage from done envelope metadata
          const isMock = (event.metadata as Record<string, unknown> | undefined)?.is_mock === true;
          if (isMock) set({ isMockLlm: true });

          // Process any actions embedded in the envelope (e.g. from agent write tools).
          // These are not emitted as separate SSE "action" events, so handle them here.
          const doneActions = (event.metadata?.actions ?? []) as ChatAction[];
          for (const action of doneActions) {
            get().dispatchAction(action);
          }

          // NOTE: layout_simplification removed — block_update event now handles this
          // via the Block Decision Engine (applyBlockDecisions).

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
      // Remove the empty assistant bubble on failure so user sees a clean error state
      set((s) => {
        const courseMsgs = s.messagesByCourse[courseId] ?? [];
        const lastMsg = courseMsgs[courseMsgs.length - 1];
        const shouldRemoveEmpty = lastMsg?.id === assistantMsg.id && !lastMsg.content;
        const nextMBC = shouldRemoveEmpty
          ? { ...s.messagesByCourse, [courseId]: courseMsgs.slice(0, -1) }
          : s.messagesByCourse;
        return {
          messagesByCourse: nextMBC,
          ...deriveActive({ ...s, messagesByCourse: nextMBC }),
          error: msg,
          errorCategory: categorizeError(e),
        };
      });
    } finally {
      const t = get()._toolStatusTimer;
      if (t) clearTimeout(t);
      set({ isStreaming: false, toolStatus: null, _abortController: null, _toolStatusTimer: null });
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
