/**
 * Tests for useRoomGenerationStream (Phase 16b Bundle B).
 *
 * We override `globalThis.EventSource` with a tiny fake that records
 * listeners and lets the test fire arbitrary `message` / `error` events
 * synchronously. That keeps assertions deterministic without spinning
 * up a real SSE server.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render } from "@testing-library/react";
import { useRoomGenerationStream } from "./use-room-generation-stream";
import type { StreamHandle } from "./use-room-generation-stream";

// ── Fake EventSource ───────────────────────────────────────────────

type Listener = (evt: MessageEvent | Event) => void;

class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;

  static instances: FakeEventSource[] = [];

  url: string;
  withCredentials: boolean;
  readyState: number = FakeEventSource.OPEN;
  closed = false;
  closeCalls = 0;

  private listeners: Record<string, Listener[]> = {};

  constructor(url: string, init?: { withCredentials?: boolean }) {
    this.url = url;
    this.withCredentials = init?.withCredentials ?? false;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, fn: Listener) {
    (this.listeners[type] ||= []).push(fn);
  }

  removeEventListener(type: string, fn: Listener) {
    const arr = this.listeners[type];
    if (!arr) return;
    this.listeners[type] = arr.filter((l) => l !== fn);
  }

  close() {
    this.closeCalls += 1;
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }

  // Test helpers ----------------------------------------------------

  emitMessage(payload: unknown) {
    const evt = new MessageEvent("message", { data: JSON.stringify(payload) });
    (this.listeners["message"] || []).forEach((fn) => fn(evt));
  }

  emitMalformed(raw: string) {
    const evt = new MessageEvent("message", { data: raw });
    (this.listeners["message"] || []).forEach((fn) => fn(evt));
  }

  emitError(readyState: number = FakeEventSource.CLOSED) {
    this.readyState = readyState;
    const evt = new Event("error");
    (this.listeners["error"] || []).forEach((fn) => fn(evt));
  }
}

// ── Harness ────────────────────────────────────────────────────────

let lastState: StreamHandle | null = null;

function Harness({ jobId }: { jobId: string | null }) {
  const state = useRoomGenerationStream(jobId);
  lastState = state;
  return null;
}

// ── Tests ──────────────────────────────────────────────────────────

describe("useRoomGenerationStream", () => {
  const originalEventSource = globalThis.EventSource;

  beforeEach(() => {
    FakeEventSource.instances = [];
    lastState = null;
    // Cast through unknown to satisfy the structural EventSource type
    // without dragging in DOM lib internals.
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
  });

  afterEach(() => {
    globalThis.EventSource = originalEventSource;
  });

  it("returns idle state when jobId is null and never opens a stream", () => {
    render(<Harness jobId={null} />);

    expect(FakeEventSource.instances).toHaveLength(0);
    expect(lastState).toMatchObject({
      status: "idle",
      progress: 0,
      roomId: null,
      pathId: null,
      error: null,
    });
    expect(typeof lastState?.disconnect).toBe("function");
  });

  it("walks through outline → tasks → persisting → completed", () => {
    render(<Harness jobId="job-1" />);

    expect(FakeEventSource.instances).toHaveLength(1);
    const source = FakeEventSource.instances[0];
    expect(source.url).toBe("/api/paths/generate-room/stream/job-1");
    expect(source.withCredentials).toBe(true);
    // Initial seeded state once jobId resolves.
    expect(lastState?.status).toBe("queued");

    act(() => source.emitMessage({ job_id: "job-1", status: "outline" }));
    expect(lastState?.status).toBe("outline");
    expect(lastState?.progress).toBe(1);

    act(() => source.emitMessage({ job_id: "job-1", status: "tasks" }));
    expect(lastState?.status).toBe("tasks");
    expect(lastState?.progress).toBe(2);

    act(() => source.emitMessage({ job_id: "job-1", status: "persisting" }));
    expect(lastState?.status).toBe("persisting");
    expect(lastState?.progress).toBe(3);

    act(() =>
      source.emitMessage({
        job_id: "job-1",
        status: "completed",
        room_id: "room-7",
        path_id: "path-3",
      }),
    );

    expect(lastState).toMatchObject({
      status: "completed",
      progress: 4,
      roomId: "room-7",
      pathId: "path-3",
      error: null,
    });
    expect(source.closeCalls).toBeGreaterThanOrEqual(1);
  });

  it("captures error_code on terminal error event", () => {
    render(<Harness jobId="job-2" />);
    const source = FakeEventSource.instances[0];

    act(() =>
      source.emitMessage({
        job_id: "job-2",
        status: "error",
        error_code: "topic_guard",
      }),
    );

    expect(lastState?.status).toBe("error");
    expect(lastState?.error?.code).toBe("topic_guard");
    expect(lastState?.roomId).toBeNull();
    expect(source.closeCalls).toBeGreaterThanOrEqual(1);
  });

  it("calls EventSource.close on unmount", () => {
    const { unmount } = render(<Harness jobId="job-3" />);
    const source = FakeEventSource.instances[0];
    expect(source.closeCalls).toBe(0);

    unmount();
    expect(source.closeCalls).toBeGreaterThanOrEqual(1);
  });

  it("closes the previous stream when jobId changes", () => {
    const { rerender } = render(<Harness jobId="job-a" />);
    const first = FakeEventSource.instances[0];

    rerender(<Harness jobId="job-b" />);
    expect(first.closeCalls).toBeGreaterThanOrEqual(1);
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[1].url).toContain("job-b");
  });

  it("ignores malformed payloads without crashing", () => {
    render(<Harness jobId="job-4" />);
    const source = FakeEventSource.instances[0];

    expect(() => act(() => source.emitMalformed("not-json{"))).not.toThrow();
    // Stayed in seeded queued state.
    expect(lastState?.status).toBe("queued");
  });

  it("disconnect() closes the EventSource immediately and returns to idle", () => {
    render(<Harness jobId="job-disconnect" />);
    const source = FakeEventSource.instances[0];
    expect(source.closeCalls).toBe(0);
    expect(lastState?.status).toBe("queued");

    // Drive a non-terminal status so we have something to clear.
    act(() =>
      source.emitMessage({ job_id: "job-disconnect", status: "outline" }),
    );
    expect(lastState?.status).toBe("outline");

    // User-initiated teardown.
    act(() => lastState?.disconnect());

    expect(source.closeCalls).toBeGreaterThanOrEqual(1);
    expect(lastState?.status).toBe("idle");
    expect(lastState?.progress).toBe(0);
    expect(lastState?.error).toBeNull();
  });

  it("disconnect() is idempotent — second call is a no-op", () => {
    render(<Harness jobId="job-idem" />);
    const source = FakeEventSource.instances[0];

    act(() => lastState?.disconnect());
    const callsAfterFirst = source.closeCalls;
    expect(callsAfterFirst).toBeGreaterThanOrEqual(1);

    // Second call: no extra close on the (now-released) EventSource.
    act(() => lastState?.disconnect());
    expect(source.closeCalls).toBe(callsAfterFirst);
  });
});
