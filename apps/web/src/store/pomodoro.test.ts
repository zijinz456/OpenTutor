import { describe, it, expect, beforeEach, vi } from "vitest";

/**
 * Pomodoro store tests (Phase 14 T3).
 *
 * The store reads `localStorage` at module construction time, so to
 * verify the "initial state from localStorage" path we re-import the
 * module fresh with `vi.resetModules()`. Same pattern as panic.test.ts.
 */

async function freshStore() {
  vi.resetModules();
  const mod = await import("./pomodoro");
  return mod.usePomodoroStore;
}

describe("usePomodoroStore", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.useRealTimers();
  });

  it("defaults: enabled=false + 25/5/15 config, idle phase", async () => {
    const store = await freshStore();
    const s = store.getState();
    expect(s.enabled).toBe(false);
    expect(s.focusMin).toBe(25);
    expect(s.shortBreakMin).toBe(5);
    expect(s.longBreakMin).toBe(15);
    expect(s.cyclesUntilLong).toBe(4);
    expect(s.chimeMuted).toBe(false);
    expect(s.phase).toBe("idle");
    expect(s.phaseStartedAt).toBe(0);
    expect(s.phaseEndsAt).toBe(0);
    expect(s.completedCycles).toBe(0);
  });

  it("localStorage persistence: updateSettings writes + reload restores", async () => {
    const store1 = await freshStore();
    store1.getState().updateSettings({ enabled: true, focusMin: 30, chimeMuted: true });

    const raw = window.localStorage.getItem("pomodoro_settings_v1");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string);
    expect(parsed.enabled).toBe(true);
    expect(parsed.focusMin).toBe(30);
    expect(parsed.chimeMuted).toBe(true);

    // Simulate reload: fresh module reads localStorage on construction.
    const store2 = await freshStore();
    const s = store2.getState();
    expect(s.enabled).toBe(true);
    expect(s.focusMin).toBe(30);
    expect(s.chimeMuted).toBe(true);
    // Phase state is NOT persisted — session starts fresh.
    expect(s.phase).toBe("idle");
  });

  it("startFocus: phase=focus + phaseEndsAt = now + focusMin*60_000", async () => {
    const store = await freshStore();
    const fakeNow = 1_700_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(fakeNow);

    store.getState().startFocus();
    const s = store.getState();
    expect(s.phase).toBe("focus");
    expect(s.phaseStartedAt).toBe(fakeNow);
    expect(s.phaseEndsAt).toBe(fakeNow + 25 * 60_000);
  });

  it("advancePhase: focus → short_break (cycles<4) → focus → ... → long_break at cycle 4", async () => {
    const store = await freshStore();
    const fakeNow = 1_700_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(fakeNow);

    // Cycle 1: focus → short_break (completedCycles 0→1)
    store.getState().startFocus();
    expect(store.getState().phase).toBe("focus");
    store.getState().advancePhase();
    expect(store.getState().phase).toBe("short_break");
    expect(store.getState().completedCycles).toBe(1);
    expect(store.getState().phaseEndsAt).toBe(fakeNow + 5 * 60_000);

    // Break → focus
    store.getState().advancePhase();
    expect(store.getState().phase).toBe("focus");
    expect(store.getState().phaseEndsAt).toBe(fakeNow + 25 * 60_000);

    // Cycle 2 → short_break (cycles=2)
    store.getState().advancePhase();
    expect(store.getState().phase).toBe("short_break");
    expect(store.getState().completedCycles).toBe(2);

    // Cycle 3 → short_break (cycles=3)
    store.getState().advancePhase(); // → focus
    store.getState().advancePhase(); // → short_break
    expect(store.getState().phase).toBe("short_break");
    expect(store.getState().completedCycles).toBe(3);

    // Cycle 4 → LONG break, cycles reset to 0
    store.getState().advancePhase(); // → focus
    store.getState().advancePhase(); // → long_break (4th focus done)
    const s = store.getState();
    expect(s.phase).toBe("long_break");
    expect(s.completedCycles).toBe(0);
    expect(s.phaseEndsAt).toBe(fakeNow + 15 * 60_000);
  });

  it("pauseSession: resets to idle", async () => {
    const store = await freshStore();
    store.getState().startFocus();
    expect(store.getState().phase).toBe("focus");

    store.getState().pauseSession();
    const s = store.getState();
    expect(s.phase).toBe("idle");
    expect(s.phaseStartedAt).toBe(0);
    expect(s.phaseEndsAt).toBe(0);
  });
});
