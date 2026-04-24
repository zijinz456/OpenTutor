import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";


async function freshStore() {
  vi.resetModules();
  const mod = await import("./bad-day");
  return mod.useBadDayStore;
}

describe("useBadDayStore", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-24T12:00:00.000Z"));
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns false on read when the persisted activation date is yesterday", async () => {
    window.localStorage.setItem(
      "ld:bad-day",
      JSON.stringify({ active: true, activated_date: "2026-04-23" }),
    );

    const useBadDayStore = await freshStore();

    expect(useBadDayStore.getState().isActiveToday()).toBe(false);
    expect(useBadDayStore.getState().active).toBe(true);
  });

  it("toggle enables bad-day for the current UTC day and persists it", async () => {
    const useBadDayStore = await freshStore();

    useBadDayStore.getState().toggle();

    expect(useBadDayStore.getState().isActiveToday()).toBe(true);
    expect(window.localStorage.getItem("ld:bad-day")).toBe(
      JSON.stringify({ active: true, activated_date: "2026-04-24" }),
    );
  });
});
