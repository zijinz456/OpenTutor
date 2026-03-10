import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useVoiceSession } from "./use-voice-session";

// --- Mocks ---

vi.mock("@/lib/auth", () => ({
  getStoredAccessToken: () => "mock-token",
}));

vi.mock("@/lib/audio-context", () => ({
  getSharedAudioContext: () => ({
    decodeAudioData: vi.fn().mockResolvedValue({ duration: 1 }),
    createBufferSource: () => ({
      connect: vi.fn(),
      start: vi.fn(),
      buffer: null,
      onended: null as (() => void) | null,
    }),
    destination: {},
    close: vi.fn(),
  }),
}));

// Mock WebSocket
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  send = vi.fn();
  close = vi.fn();

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  /** Simulate server opening the connection */
  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  /** Simulate receiving a server message */
  simulateMessage(data: Record<string, unknown>) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  }

  /** Simulate connection error */
  simulateError() {
    this.onerror?.(new Event("error"));
  }

  /** Simulate clean close */
  simulateClose(wasClean = true) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({ wasClean, code: 1000, reason: "" } as CloseEvent);
  }

  static instances: MockWebSocket[] = [];
  static reset() {
    MockWebSocket.instances = [];
  }
  static latest() {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1];
  }
}

// Replace global WebSocket
const OriginalWebSocket = globalThis.WebSocket;
beforeEach(() => {
  MockWebSocket.reset();
  (globalThis as Record<string, unknown>).WebSocket = MockWebSocket as unknown as typeof WebSocket;
  // Copy static constants
  (globalThis.WebSocket as unknown as Record<string, number>).OPEN = MockWebSocket.OPEN;
  (globalThis.WebSocket as unknown as Record<string, number>).CONNECTING = MockWebSocket.CONNECTING;
});

afterEach(() => {
  globalThis.WebSocket = OriginalWebSocket;
  vi.restoreAllMocks();
});

describe("useVoiceSession", () => {
  it("initializes with idle state", () => {
    const { result } = renderHook(() => useVoiceSession("course-1"));

    expect(result.current.voiceState).toBe("idle");
    expect(result.current.isConnected).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.transcript).toBe("");
    expect(result.current.agentText).toBe("");
  });

  it("connects and sends config on open", async () => {
    const { result } = renderHook(() =>
      useVoiceSession("course-1", { ttsVoice: "nova", ttsEnabled: true }),
    );

    let connectPromise: Promise<unknown>;
    act(() => {
      connectPromise = result.current.connect();
    });

    expect(result.current.voiceState).toBe("connecting");

    const ws = MockWebSocket.latest();
    expect(ws.url).toContain("/api/voice/ws/course-1");
    expect(ws.url).toContain("token=mock-token");

    act(() => {
      ws.simulateOpen();
    });

    await act(async () => {
      await connectPromise!;
    });

    expect(result.current.voiceState).toBe("idle");
    expect(result.current.isConnected).toBe(true);
    expect(ws.send).toHaveBeenCalledWith(
      expect.stringContaining('"tts_voice":"nova"'),
    );
  });

  it("sets error on connection failure", async () => {
    const { result } = renderHook(() => useVoiceSession("course-1"));

    let connectPromise: Promise<unknown>;
    act(() => {
      connectPromise = result.current.connect().catch(() => {});
    });

    const ws = MockWebSocket.latest();
    act(() => {
      ws.simulateError();
    });

    await act(async () => {
      await connectPromise;
    });

    expect(result.current.error).toBe("Voice connection failed");
    expect(result.current.isConnected).toBe(false);
  });

  it("handles transcript message", async () => {
    const { result } = renderHook(() => useVoiceSession("course-1"));

    // Connect first
    let connectPromise: Promise<unknown>;
    act(() => {
      connectPromise = result.current.connect();
    });
    const ws = MockWebSocket.latest();
    act(() => { ws.simulateOpen(); });
    await act(async () => { await connectPromise!; });

    // Receive transcript
    act(() => {
      ws.simulateMessage({ type: "transcript", text: "Hello world" });
    });

    expect(result.current.transcript).toBe("Hello world");
    expect(result.current.voiceState).toBe("processing");
  });

  it("accumulates agent text from message events", async () => {
    const { result } = renderHook(() => useVoiceSession("course-1"));

    let connectPromise: Promise<unknown>;
    act(() => {
      connectPromise = result.current.connect();
    });
    const ws = MockWebSocket.latest();
    act(() => { ws.simulateOpen(); });
    await act(async () => { await connectPromise!; });

    act(() => {
      ws.simulateMessage({ type: "message", content: "Hello " });
      ws.simulateMessage({ type: "message", content: "world" });
    });

    expect(result.current.agentText).toBe("Hello world");
  });

  it("handles error message from server", async () => {
    const { result } = renderHook(() => useVoiceSession("course-1"));

    let connectPromise: Promise<unknown>;
    act(() => {
      connectPromise = result.current.connect();
    });
    const ws = MockWebSocket.latest();
    act(() => { ws.simulateOpen(); });
    await act(async () => { await connectPromise!; });

    act(() => {
      ws.simulateMessage({ type: "error", message: "Server overloaded" });
    });

    expect(result.current.error).toBe("Server overloaded");
    expect(result.current.voiceState).toBe("idle");
  });

  it("handles done message and resets buffers", async () => {
    const { result } = renderHook(() => useVoiceSession("course-1"));

    let connectPromise: Promise<unknown>;
    act(() => {
      connectPromise = result.current.connect();
    });
    const ws = MockWebSocket.latest();
    act(() => { ws.simulateOpen(); });
    await act(async () => { await connectPromise!; });

    // Set some state first
    act(() => {
      ws.simulateMessage({ type: "transcript", text: "test" });
      ws.simulateMessage({ type: "message", content: "response" });
    });

    expect(result.current.transcript).toBe("test");
    expect(result.current.agentText).toBe("response");

    act(() => {
      ws.simulateMessage({ type: "done" });
    });

    expect(result.current.transcript).toBe("");
    expect(result.current.agentText).toBe("");
    expect(result.current.voiceState).toBe("idle");
  });

  it("disconnect cleans up WebSocket and resets state", async () => {
    const { result } = renderHook(() => useVoiceSession("course-1"));

    let connectPromise: Promise<unknown>;
    act(() => {
      connectPromise = result.current.connect();
    });
    const ws = MockWebSocket.latest();
    act(() => { ws.simulateOpen(); });
    await act(async () => { await connectPromise!; });

    expect(result.current.isConnected).toBe(true);

    act(() => {
      result.current.disconnect();
    });

    expect(ws.close).toHaveBeenCalled();
    expect(result.current.isConnected).toBe(false);
    expect(result.current.voiceState).toBe("idle");
  });

  it("reuses existing open connection", async () => {
    const { result } = renderHook(() => useVoiceSession("course-1"));

    // First connect
    let p: Promise<unknown>;
    act(() => { p = result.current.connect(); });
    const ws = MockWebSocket.latest();
    act(() => { ws.simulateOpen(); });
    await act(async () => { await p!; });

    // Second connect should reuse
    await act(async () => {
      await result.current.connect();
    });

    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("handles status message with speaking phase", async () => {
    const { result } = renderHook(() => useVoiceSession("course-1"));

    let connectPromise: Promise<unknown>;
    act(() => { connectPromise = result.current.connect(); });
    const ws = MockWebSocket.latest();
    act(() => { ws.simulateOpen(); });
    await act(async () => { await connectPromise!; });

    act(() => {
      ws.simulateMessage({ type: "status", phase: "speaking" });
    });

    expect(result.current.voiceState).toBe("playing");
  });

  it("includes access token in WebSocket URL", () => {
    const { result } = renderHook(() =>
      useVoiceSession("course-1", { accessToken: "custom-token" }),
    );

    act(() => {
      void result.current.connect().catch(() => {});
    });

    const ws = MockWebSocket.latest();
    expect(ws.url).toContain("token=custom-token");
  });
});
