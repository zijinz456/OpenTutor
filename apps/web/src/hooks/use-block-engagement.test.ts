import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("use-block-engagement sync flush", () => {
  beforeEach(() => {
    vi.resetModules();
    mockFetch.mockReset();
    localStorage.clear();
    localStorage.setItem("access_token", "token-sync");
    document.cookie = "csrf_token=csrf-sync;path=/";
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
  });

  it("flushes buffered events on page hide with auth+csrf headers and credentials", async () => {
    const { recordBlockEvent } = await import("./use-block-engagement");
    recordBlockEvent("course-1", "notes", "approve");

    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    window.dispatchEvent(new Event("visibilitychange"));

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(init.keepalive).toBe(true);
    expect(init.credentials).toBe("include");
    expect(headers.get("Authorization")).toBe("Bearer token-sync");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-sync");
    expect(headers.get("Content-Type")).toBe("application/json");
  });
});
