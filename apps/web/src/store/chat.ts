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
  streamChat,
  type ChatAction,
  type ChatHistoryMessage,
  type ChatSessionSummary,
} from "@/lib/api";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

export interface SendMessageOptions {
  activeTab?: string;
  tabContext?: Record<string, unknown>;
  scene?: string;
}

interface ChatState {
  activeCourseId: string | null;
  messagesByCourse: Record<string, ChatMessage[]>;
  sessionIds: Record<string, string>;
  sessionsByCourse: Record<string, ChatSessionSummary[]>;
  messages: ChatMessage[];
  isStreaming: boolean;
  isLoadingSessions: boolean;
  error: string | null;
  /** AbortController for cancelling active stream */
  _abortController: AbortController | null;
  abortStream: () => void;

  /** Active tool status from ReAct agent loop (null when no tool running). */
  toolStatus: { tool: string; status: "running" | "complete" } | null;

  /** Callback for NL actions (layout changes, preference updates, scene switch). Set by CoursePage. */
  onAction: ((action: ChatAction) => void) | null;
  setOnAction: (cb: (action: ChatAction) => void) => void;
  setCourseContext: (courseId: string) => void;
  loadSessions: (courseId: string, options?: { restoreLatest?: boolean }) => Promise<void>;
  loadSessionMessages: (courseId: string, sessionId: string) => Promise<void>;
  startNewSession: (courseId: string) => void;

  sendMessage: (courseId: string, content: string, options?: SendMessageOptions) => Promise<void>;
  clearMessages: (courseId?: string) => void;
}

let messageCounter = 0;

export const useChatStore = create<ChatState>((set, get) => ({
  activeCourseId: null,
  messagesByCourse: {},
  sessionIds: {},
  sessionsByCourse: {},
  messages: [],
  isStreaming: false,
  isLoadingSessions: false,
  error: null,
  toolStatus: null,
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
    set((s) => ({
      activeCourseId: courseId,
      messages: s.messagesByCourse[courseId] ?? [],
      error: null,
    })),
  loadSessions: async (courseId, options) => {
    set({ isLoadingSessions: true, error: null });
    try {
      const sessions = await listChatSessions(courseId);
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
      const result = await getChatSessionMessages(sessionId);
      const hydratedMessages: ChatMessage[] = result.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        timestamp: message.created_at ? new Date(message.created_at) : new Date(),
      }));
      set((s) => ({
        activeCourseId: courseId,
        messages: hydratedMessages,
        messagesByCourse: {
          ...s.messagesByCourse,
          [courseId]: hydratedMessages,
        },
        sessionIds: {
          ...s.sessionIds,
          [courseId]: sessionId,
        },
      }));
    } catch (e) {
      set({ error: (e as Error).message });
    } finally {
      set({ isLoadingSessions: false });
    }
  },
  startNewSession: (courseId) =>
    set((s) => ({
      activeCourseId: courseId,
      messages: [],
      messagesByCourse: {
        ...s.messagesByCourse,
        [courseId]: [],
      },
      sessionIds: Object.fromEntries(
        Object.entries(s.sessionIds).filter(([key]) => key !== courseId),
      ),
      error: null,
    })),

  sendMessage: async (courseId, content, options?) => {
    if (get().activeCourseId !== courseId) {
      get().setCourseContext(courseId);
    }

    const userMsg: ChatMessage = {
      id: `msg-${++messageCounter}`,
      role: "user",
      content,
      timestamp: new Date(),
    };

    const assistantMsg: ChatMessage = {
      id: `msg-${++messageCounter}`,
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

    set((s) => ({
      messages: [...s.messages, userMsg, assistantMsg],
      messagesByCourse: {
        ...s.messagesByCourse,
        [courseId]: [...(s.messagesByCourse[courseId] ?? []), userMsg, assistantMsg],
      },
      isStreaming: true,
      error: null,
    }));

    const controller = new AbortController();
    set({ _abortController: controller });
    try {
      for await (const event of streamChat({
        courseId,
        message: content,
        activeTab: options?.activeTab,
        tabContext: options?.tabContext,
        scene: options?.scene,
        sessionId: get().sessionIds[courseId],
        history,
        signal: controller.signal,
      })) {
        if (event.type === "content") {
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: m.content + event.content } : m,
            ),
            messagesByCourse: {
              ...s.messagesByCourse,
              [courseId]: (s.messagesByCourse[courseId] ?? []).map((m) =>
                m.id === assistantMsg.id ? { ...m, content: m.content + event.content } : m,
              ),
            },
          }));
        } else if (event.type === "action") {
          const { onAction } = get();
          if (onAction) {
            onAction(event.action);
          }
        } else if (event.type === "tool_status") {
          set({ toolStatus: { tool: event.tool, status: event.status } });
          if (event.status === "complete") {
            setTimeout(() => set({ toolStatus: null }), 1500);
          }
        } else if (event.type === "replace") {
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: event.content } : m,
            ),
            messagesByCourse: {
              ...s.messagesByCourse,
              [courseId]: (s.messagesByCourse[courseId] ?? []).map((m) =>
                m.id === assistantMsg.id ? { ...m, content: event.content } : m,
              ),
            },
          }));
        } else if (event.type === "done" && event.sessionId) {
          set((s) => ({
            sessionIds: {
              ...s.sessionIds,
              [courseId]: event.sessionId!,
            },
          }));
        }
      }
      await get().loadSessions(courseId);
    } catch (e) {
      set({ error: (e as Error).message });
    } finally {
      set({ isStreaming: false, toolStatus: null, _abortController: null });
    }
  },

  clearMessages: (courseId) =>
    set((s) => {
      const targetCourseId = courseId ?? s.activeCourseId;
      if (!targetCourseId) {
        return { messages: [], error: null, sessionIds: {} };
      }

      const nextMessagesByCourse = { ...s.messagesByCourse };
      delete nextMessagesByCourse[targetCourseId];

      const nextSessionIds = { ...s.sessionIds };
      delete nextSessionIds[targetCourseId];

      return {
        messages: s.activeCourseId === targetCourseId ? [] : s.messages,
        messagesByCourse: nextMessagesByCourse,
        sessionIds: nextSessionIds,
        error: null,
      };
    }),
}));
