/**
 * Chat store using Zustand.
 * Manages conversation messages, streaming state, and NL action dispatching.
 *
 * Phase 0-B: Handles [ACTION:...] markers from LLM responses (CopilotKit pattern).
 */

import { create } from "zustand";
import { streamChat, type ChatAction } from "@/lib/api";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface ChatState {
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;

  /** Callback for NL actions (layout changes, preference updates). Set by CoursePage. */
  onAction: ((action: ChatAction) => void) | null;
  setOnAction: (cb: (action: ChatAction) => void) => void;

  sendMessage: (courseId: string, content: string) => Promise<void>;
  clearMessages: () => void;
}

let messageCounter = 0;

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isStreaming: false,
  error: null,
  onAction: null,

  setOnAction: (cb) => set({ onAction: cb }),

  sendMessage: async (courseId, content) => {
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

    set((s) => ({
      messages: [...s.messages, userMsg, assistantMsg],
      isStreaming: true,
      error: null,
    }));

    try {
      for await (const event of streamChat(courseId, content)) {
        if (event.type === "content") {
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === assistantMsg.id ? { ...m, content: m.content + event.content } : m,
            ),
          }));
        } else if (event.type === "action") {
          const { onAction } = get();
          if (onAction) {
            onAction(event.action);
          }
        }
      }
    } catch (e) {
      set({ error: (e as Error).message });
    } finally {
      set({ isStreaming: false });
    }
  },

  clearMessages: () => set({ messages: [], error: null }),
}));
