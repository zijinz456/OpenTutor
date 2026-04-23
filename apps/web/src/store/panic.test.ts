import { describe, it, expect, beforeEach, vi } from "vitest";

/**
 * Panic store tests (Phase 14 T2).
 *
 * The store reads `localStorage.getItem("panic_mode_on")` at module
 * construction time, so to verify the "initial state from localStorage"
 * path we must seed storage *before* the module loads. We use
 * `vi.resetModules()` + `await import(...)` to get a freshly-constructed
 * store on each test that cares about the initial value.
 */

async function freshStore() {
  vi.resetModules();
  const mod = await import("./panic");
  return mod.usePanicStore;
}

describe("usePanicStore", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("initial state reflects 'true' in localStorage", async () => {
    window.localStorage.setItem("panic_mode_on", "true");
    const usePanicStore = await freshStore();
    const s = usePanicStore.getState();
    expect(s.enabled).toBe(true);
    expect(typeof s.enabledAt).toBe("number");
  });

  it("toggle flips state and writes localStorage", async () => {
    const usePanicStore = await freshStore();
    // Starts disabled because beforeEach cleared storage before import.
    expect(usePanicStore.getState().enabled).toBe(false);

    usePanicStore.getState().toggle();
    expect(usePanicStore.getState().enabled).toBe(true);
    expect(window.localStorage.getItem("panic_mode_on")).toBe("true");
    expect(typeof usePanicStore.getState().enabledAt).toBe("number");

    usePanicStore.getState().toggle();
    expect(usePanicStore.getState().enabled).toBe(false);
    expect(window.localStorage.getItem("panic_mode_on")).toBe("false");
    expect(usePanicStore.getState().enabledAt).toBeNull();
  });

  it("disable() clears enabledAt and writes 'false' to localStorage", async () => {
    const usePanicStore = await freshStore();
    usePanicStore.getState().enable();
    expect(usePanicStore.getState().enabled).toBe(true);

    usePanicStore.getState().disable();
    expect(usePanicStore.getState().enabled).toBe(false);
    expect(usePanicStore.getState().enabledAt).toBeNull();
    expect(window.localStorage.getItem("panic_mode_on")).toBe("false");
  });
});
