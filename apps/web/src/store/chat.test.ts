import { describe, it, expect, vi, beforeEach } from "vitest";
import { useChatStore } from "./chat";
import { toast } from "sonner";

// Mock API functions
vi.mock("@/lib/api", () => ({
  getChatSessionMessages: vi.fn(),
  listChatSessions: vi.fn(),
  streamChat: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    warning: vi.fn(),
  },
}));

vi.mock("@/lib/cache", () => ({
  ttlCache: {
    get: vi.fn(() => null),
    set: vi.fn(),
    invalidate: vi.fn(),
  },
}));

vi.mock("@/store/workspace", () => ({
  useWorkspaceStore: {
    getState: () => ({
      triggerSectionRefresh: vi.fn(),
      spaceLayout: { mode: "course_following", blocks: [] },
    }),
  },
}));

import {
  listChatSessions,
  streamChat,
} from "@/lib/api";

const mockListChatSessions = vi.mocked(listChatSessions);
const mockStreamChat = vi.mocked(streamChat);

function resetStore() {
  useChatStore.setState({
    activeCourseId: null,
    messagesByCourse: {},
    sessionIds: {},
    sessionsByCourse: {},
    planProgressByCourse: {},
    messages: [],
    activePlan: null,
    generatedQuizDraftByCourse: {},
    generatedQuizErrorByCourse: {},
    generatedQuizDraft: null,
    generatedQuizError: null,
    isStreaming: false,
    isLoadingSessions: false,
    error: null,
    errorCategory: null,
    isMockLlm: false,
    _abortController: null,
    _toolStatusTimer: null,
    _slowAnalyzingTimer: null,
    _slowDelayedTimer: null,
    streamPhase: null,
    slowState: null,
    latestWarning: null,
    toolStatus: null,
    clarifyOptions: null,
    actionHandlers: {},
    actionHandlerOrder: [],
  });
}

describe("useChatStore", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
    mockListChatSessions.mockResolvedValue([] as never);
  });

  describe("setCourseContext", () => {
    it("sets active course and derives messages", () => {
      const msgs = [
        { id: "m1", role: "user" as const, content: "Hello", timestamp: new Date() },
      ];
      useChatStore.setState({
        messagesByCourse: { "c1": msgs },
      });

      useChatStore.getState().setCourseContext("c1");

      const state = useChatStore.getState();
      expect(state.activeCourseId).toBe("c1");
      expect(state.messages).toEqual(msgs);
    });

    it("returns empty messages for unknown course", () => {
      useChatStore.getState().setCourseContext("unknown");
      expect(useChatStore.getState().messages).toEqual([]);
    });
  });

  describe("clearMessages", () => {
    it("clears messages for active course", () => {
      useChatStore.setState({
        activeCourseId: "c1",
        messagesByCourse: {
          c1: [{ id: "m1", role: "user", content: "test", timestamp: new Date() }],
        },
        messages: [{ id: "m1", role: "user", content: "test", timestamp: new Date() }],
      });

      useChatStore.getState().clearMessages("c1");

      expect(useChatStore.getState().messages).toEqual([]);
    });
  });

  describe("loadSessions", () => {
    it("loads and caches chat sessions", async () => {
      const sessions = [
        { id: "s1", title: "Session 1", created_at: "2026-01-01", message_count: 5 },
      ];
      mockListChatSessions.mockResolvedValueOnce(sessions as never);

      await useChatStore.getState().loadSessions("c1");

      expect(useChatStore.getState().sessionsByCourse["c1"]).toEqual(sessions);
      expect(useChatStore.getState().isLoadingSessions).toBe(false);
    });
  });

  describe("startNewSession", () => {
    it("clears session ID and messages for course", () => {
      useChatStore.setState({
        activeCourseId: "c1",
        sessionIds: { c1: "old-session" },
        messagesByCourse: {
          c1: [{ id: "m1", role: "user", content: "old", timestamp: new Date() }],
        },
        messages: [{ id: "m1", role: "user", content: "old", timestamp: new Date() }],
      });

      useChatStore.getState().startNewSession("c1");

      const state = useChatStore.getState();
      expect(state.sessionIds["c1"]).toBeUndefined();
      expect(state.messages).toEqual([]);
    });
  });

  describe("abortStream", () => {
    it("aborts the active stream controller", () => {
      const controller = new AbortController();
      useChatStore.setState({
        _abortController: controller,
        isStreaming: true,
      });

      useChatStore.getState().abortStream();

      expect(controller.signal.aborted).toBe(true);
      expect(useChatStore.getState().isStreaming).toBe(false);
    });
  });

  describe("error handling", () => {
    it("initializes with no error", () => {
      expect(useChatStore.getState().error).toBeNull();
      expect(useChatStore.getState().errorCategory).toBeNull();
    });

    it("shows a toast when the stream emits a warning", async () => {
      mockStreamChat.mockReturnValueOnce((async function* () {
        yield {
          type: "warning" as const,
          warningType: "adaptation_degraded",
          message: "Advanced adaptation is temporarily unavailable.",
        };
        yield {
          type: "done" as const,
          sessionId: "session-1",
          metadata: {},
        };
      })());

      await useChatStore.getState().sendMessage("c1", "help me understand recursion");

      expect(toast.warning).toHaveBeenCalledWith("Advanced adaptation is temporarily unavailable.");
    });

    it("detects a generated quiz draft only after the stream completes", async () => {
      mockStreamChat.mockReturnValueOnce((async function* () {
        yield {
          type: "content" as const,
          content: JSON.stringify([
            {
              question_type: "mc",
              question: "What must be true before binary search works?",
              options: { A: "Sorted data", B: "Unique data", C: "Prime length", D: "Recursive code" },
              correct_answer: "A",
              explanation: "Binary search relies on sorted order.",
              difficulty_layer: 1,
              problem_metadata: { core_concept: "binary search prerequisite" },
            },
          ]),
        };
        yield {
          type: "done" as const,
          sessionId: "session-1",
          metadata: {},
        };
      })());

      await useChatStore.getState().sendMessage("c1", "generate 1 quiz question as JSON");

      expect(useChatStore.getState().generatedQuizDraftByCourse["c1"]?.questionCount).toBe(1);
      expect(useChatStore.getState().generatedQuizErrorByCourse["c1"]).toBeNull();
    });
  });

  describe("action handler lifecycle", () => {
    it("registers and unregisters handlers", () => {
      const handlerA = vi.fn();
      const handlerB = vi.fn();
      const action = { action: "data_updated" as const, value: "notes" };

      const unregisterA = useChatStore.getState().registerOnAction(handlerA);
      const unregisterB = useChatStore.getState().registerOnAction(handlerB);
      useChatStore.getState().dispatchAction(action);

      expect(handlerA).toHaveBeenCalledWith(action);
      expect(handlerB).toHaveBeenCalledWith(action);

      unregisterA();
      unregisterB();
      useChatStore.getState().dispatchAction(action);

      expect(handlerA).toHaveBeenCalledTimes(1);
      expect(handlerB).toHaveBeenCalledTimes(1);
      expect(useChatStore.getState().actionHandlerOrder).toHaveLength(0);
    });

    it("runs fallback handler only when no primary handlers are registered", () => {
      const fallback = vi.fn();
      const primary = vi.fn();
      const action = { action: "focus_topic" as const, value: "node-1" };

      const unregisterFallback = useChatStore.getState().registerFallbackOnAction(fallback);
      useChatStore.getState().dispatchAction(action);
      expect(fallback).toHaveBeenCalledTimes(1);

      const unregisterPrimary = useChatStore.getState().registerOnAction(primary);
      useChatStore.getState().dispatchAction(action);
      expect(primary).toHaveBeenCalledTimes(1);
      expect(fallback).toHaveBeenCalledTimes(1);

      unregisterPrimary();
      useChatStore.getState().dispatchAction(action);
      expect(fallback).toHaveBeenCalledTimes(2);

      unregisterFallback();
    });
  });
});
