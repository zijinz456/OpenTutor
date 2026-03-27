import { beforeEach, describe, expect, it, vi } from "vitest";
import { streamChat } from "./chat";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("streamChat", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    localStorage.clear();
    document.cookie = "csrf_token=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/";
  });

  it("sends auth + csrf headers with credentials include", async () => {
    localStorage.setItem("access_token", "token-123");
    document.cookie = "csrf_token=csrf-123;path=/";
    mockFetch.mockResolvedValueOnce(
      new Response("event: done\ndata: {}\n\n", {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    for await (const event of streamChat({ courseId: "course-1", message: "hello" })) {
      if (event.type === "done") break;
    }

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/chat");
    const headers = new Headers(init.headers);
    expect(init.credentials).toBe("include");
    expect(headers.get("Authorization")).toBe("Bearer token-123");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-123");
    expect(headers.get("Content-Type")).toBe("application/json");
  });
});
