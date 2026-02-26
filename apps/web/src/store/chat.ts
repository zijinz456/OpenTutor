/**
 * Chat store using Zustand.
 * Manages conversation messages and streaming state.
 */

import { create } from "zustand";
import { streamChat } from "@/lib/api";

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

  sendMessage: (courseId: string, content: string) => Promise<void>;
  clearMessages: () => void;
}

let messageCounter = 0;

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isStreaming: false,
  error: null,

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
      for await (const chunk of streamChat(courseId, content)) {
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === assistantMsg.id ? { ...m, content: m.content + chunk } : m,
          ),
        }));
      }
    } catch (e) {
      set({ error: (e as Error).message });
    } finally {
      set({ isStreaming: false });
    }
  },

  clearMessages: () => set({ messages: [], error: null }),
}));
