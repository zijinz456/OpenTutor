import { describe, it, expect, vi, beforeEach, afterEach, afterAll } from "vitest";
import { request, requestBlob, ApiError, parseApiError, API_BASE } from "./client";

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);
const mockBuildAuthHeaders = vi.fn((headers: Headers) => headers);

// Mock auth module
vi.mock("@/lib/auth", () => ({
  buildAuthHeaders: (headers: Headers) => mockBuildAuthHeaders(headers),
}));

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("API_BASE", () => {
  it("defaults to relative /api path", () => {
    expect(API_BASE).toBe("/api");
  });
});

describe("parseApiError", () => {
  it("extracts detail from API error response", async () => {
    const res = jsonResponse({ detail: "Not found", code: "not_found" }, 404);
    const err = await parseApiError(res);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.code).toBe("not_found");
    expect(err.message).toBe("Not found");
  });

  it("handles non-JSON error response", async () => {
    const res = new Response("Server Error", {
      status: 500,
      statusText: "Internal Server Error",
    });
    const err = await parseApiError(res);
    expect(err.status).toBe(500);
    expect(err.message).toBe("Internal Server Error");
  });
});

describe("request", () => {
  const randomSpy = vi.spyOn(Math, "random").mockReturnValue(0);

  beforeEach(() => {
    mockFetch.mockReset();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  afterAll(() => {
    randomSpy.mockRestore();
  });

  it("makes a GET request and returns parsed JSON", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ id: 1, name: "test" }));
    const result = await request<{ id: number; name: string }>("/courses");
    expect(result).toEqual({ id: 1, name: "test" });
    expect(mockFetch).toHaveBeenCalledWith(
      `${API_BASE}/courses`,
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("handles 204 No Content", async () => {
    mockFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const result = await request("/courses/1", { method: "DELETE" });
    expect(result).toBeUndefined();
  });

  it("throws ApiError on 4xx without retrying", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({ detail: "Not found", code: "not_found" }, 404)
    );
    await expect(request("/courses/missing")).rejects.toThrow(ApiError);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("retries on 5xx errors", async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ detail: "Server error" }, 500))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));

    const promise = request<{ ok: boolean }>("/health");
    await vi.advanceTimersByTimeAsync(2000);
    const result = await promise;
    expect(result).toEqual({ ok: true });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("retries on network errors (TypeError)", async () => {
    mockFetch
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));

    const promise = request<{ ok: boolean }>("/health");
    await vi.advanceTimersByTimeAsync(2000);
    const result = await promise;
    expect(result).toEqual({ ok: true });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("throws after exhausting retries", async () => {
    vi.useRealTimers(); // Use real timers; delays are mocked via short timeout
    // Create a version of request that will fail fast
    mockFetch.mockImplementation(async () => jsonResponse({ detail: "Server error" }, 500));

    // Override setTimeout to resolve immediately
    const origSetTimeout = globalThis.setTimeout;
    globalThis.setTimeout = ((fn: () => void) => origSetTimeout(fn, 0)) as typeof setTimeout;

    try {
      await expect(request("/health")).rejects.toThrow(ApiError);
      expect(mockFetch).toHaveBeenCalledTimes(5); // 1 initial + 4 retries
    } finally {
      globalThis.setTimeout = origSetTimeout;
    }
  });
});

describe("requestBlob", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockBuildAuthHeaders.mockClear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns blob payload and filename from content-disposition", async () => {
    mockFetch.mockResolvedValueOnce(new Response("file-content", {
      status: 200,
      headers: {
        "Content-Type": "text/plain",
        "Content-Disposition": "attachment; filename=test-export.csv",
      },
    }));

    const result = await requestBlob("/export/session");
    expect(await result.blob.text()).toBe("file-content");
    expect(result.fileName).toBe("test-export.csv");
    expect(result.contentType).toBe("text/plain");
    expect(mockFetch).toHaveBeenCalledWith(
      `${API_BASE}/export/session`,
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("throws ApiError on non-2xx response", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({ detail: "Unauthorized", code: "unauthorized" }, 401),
    );

    await expect(requestBlob("/export/session")).rejects.toThrow(ApiError);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("applies auth header builder for binary requests", async () => {
    mockFetch.mockResolvedValueOnce(new Response("ok", { status: 200 }));

    await requestBlob("/export/session");

    expect(mockBuildAuthHeaders).toHaveBeenCalledTimes(1);
  });
});
