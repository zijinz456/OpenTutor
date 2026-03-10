import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ttlCache } from "./cache";

describe("TtlCache", () => {
  beforeEach(() => {
    ttlCache.invalidateAll();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("stores and retrieves values", () => {
    ttlCache.set("key", { data: 42 }, 5000);
    expect(ttlCache.get("key")).toEqual({ data: 42 });
  });

  it("returns undefined for missing keys", () => {
    expect(ttlCache.get("nonexistent")).toBeUndefined();
  });

  it("expires entries after TTL", () => {
    ttlCache.set("key", "value", 1000);
    expect(ttlCache.get("key")).toBe("value");

    vi.advanceTimersByTime(1001);
    expect(ttlCache.get("key")).toBeUndefined();
  });

  it("has() returns correct status", () => {
    ttlCache.set("key", "value", 5000);
    expect(ttlCache.has("key")).toBe(true);
    expect(ttlCache.has("missing")).toBe(false);
  });

  it("invalidate() removes a specific key", () => {
    ttlCache.set("a", 1, 5000);
    ttlCache.set("b", 2, 5000);
    ttlCache.invalidate("a");
    expect(ttlCache.get("a")).toBeUndefined();
    expect(ttlCache.get("b")).toBe(2);
  });

  it("invalidateAll() clears everything", () => {
    ttlCache.set("a", 1, 5000);
    ttlCache.set("b", 2, 5000);
    ttlCache.invalidateAll();
    expect(ttlCache.get("a")).toBeUndefined();
    expect(ttlCache.get("b")).toBeUndefined();
  });

  it("overwrites existing entries", () => {
    ttlCache.set("key", "old", 5000);
    ttlCache.set("key", "new", 5000);
    expect(ttlCache.get("key")).toBe("new");
  });
});
