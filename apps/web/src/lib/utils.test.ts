import { describe, it, expect, beforeEach } from "vitest";
import { cn, safeLocalStorage } from "./utils";

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("px-2", "py-1")).toBe("px-2 py-1");
  });

  it("handles conflicting tailwind classes", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
  });

  it("handles conditional classes", () => {
    expect(cn("base", false && "hidden", "visible")).toBe("base visible");
  });
});

describe("safeLocalStorage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns fallback when key does not exist", () => {
    expect(safeLocalStorage.get("missing", "default")).toBe("default");
  });

  it("stores and retrieves values", () => {
    safeLocalStorage.set("key", { a: 1 });
    expect(safeLocalStorage.get("key", null)).toEqual({ a: 1 });
  });

  it("removes values", () => {
    safeLocalStorage.set("key", "val");
    safeLocalStorage.remove("key");
    expect(safeLocalStorage.get("key", "gone")).toBe("gone");
  });

  it("handles corrupt JSON gracefully", () => {
    localStorage.setItem("bad", "not-json");
    expect(safeLocalStorage.get("bad", "fallback")).toBe("fallback");
    // corrupt key should be removed
    expect(localStorage.getItem("bad")).toBeNull();
  });
});
