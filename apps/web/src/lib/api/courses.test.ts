import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { scrapeUrl, uploadFile } from "./courses";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("courses API secure request behavior", () => {
  const originalXmlHttpRequest = globalThis.XMLHttpRequest;

  beforeEach(() => {
    mockFetch.mockReset();
    localStorage.clear();
    localStorage.setItem("access_token", "token-abc");
    document.cookie = "csrf_token=csrf-abc;path=/";
  });

  afterEach(() => {
    globalThis.XMLHttpRequest = originalXmlHttpRequest;
    document.cookie = "csrf_token=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/";
  });

  it("uploadFile fetch branch includes auth + csrf + credentials without forcing content-type", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ nodes_created: 1 }));
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });

    await uploadFile("course-1", file);

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(init.credentials).toBe("include");
    expect(headers.get("Authorization")).toBe("Bearer token-abc");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-abc");
    expect(headers.get("Content-Type")).toBeNull();
  });

  it("scrapeUrl includes auth + csrf + credentials without forcing content-type", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ nodes_created: 2 }));

    await scrapeUrl("course-1", "https://example.com/course");

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(init.credentials).toBe("include");
    expect(headers.get("Authorization")).toBe("Bearer token-abc");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-abc");
    expect(headers.get("Content-Type")).toBeNull();
  });

  it("uploadFile xhr branch applies auth + csrf headers and withCredentials", async () => {
    class FakeXMLHttpRequest {
      static instance: FakeXMLHttpRequest | null = null;

      method = "";
      url = "";
      withCredentials = false;
      status = 200;
      responseText = JSON.stringify({ nodes_created: 3 });
      requestHeaders: Record<string, string> = {};
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      upload = {
        onprogress: null as ((event: ProgressEvent) => void) | null,
      };

      constructor() {
        FakeXMLHttpRequest.instance = this;
      }

      open(method: string, url: string) {
        this.method = method;
        this.url = url;
      }

      setRequestHeader(key: string, value: string) {
        this.requestHeaders[key] = value;
      }

      send() {
        this.upload.onprogress?.({
          lengthComputable: true,
          loaded: 5,
          total: 10,
        } as ProgressEvent);
        this.onload?.();
      }
    }

    globalThis.XMLHttpRequest = FakeXMLHttpRequest as unknown as typeof XMLHttpRequest;
    const progress = vi.fn();
    const file = new File(["payload"], "upload.txt", { type: "text/plain" });

    const result = await uploadFile("course-1", file, progress);
    const xhr = FakeXMLHttpRequest.instance;

    expect(result).toEqual({ nodes_created: 3 });
    expect(progress).toHaveBeenCalledWith(50);
    expect(xhr?.withCredentials).toBe(true);
    expect(xhr?.requestHeaders.authorization).toBe("Bearer token-abc");
    expect(xhr?.requestHeaders["x-csrf-token"]).toBe("csrf-abc");
    expect(xhr?.requestHeaders["Content-Type"]).toBeUndefined();
  });
});
