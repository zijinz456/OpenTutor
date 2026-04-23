/**
 * Unit tests for the voice transcription client (Phase 8 T3).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, transcribeAudio } from "./voice";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("transcribeAudio", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("POSTs FormData with file + language hint", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        text: "hello world",
        language: "en",
        duration_ms: 1500,
      }),
    );
    const blob = new Blob([new Uint8Array(64)], { type: "audio/webm" });
    const out = await transcribeAudio(blob, "en");

    expect(out).toEqual({
      text: "hello world",
      language: "en",
      duration_ms: 1500,
    });
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/voice/transcribe");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    const form = init.body as FormData;
    const filePart = form.get("file");
    expect(filePart).toBeInstanceOf(Blob);
    expect(form.get("language")).toBe("en");
  });

  it("non-2xx response throws ApiError with detail", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Unsupported audio format" }, 415),
    );
    const blob = new Blob([new Uint8Array(8)], { type: "audio/webm" });
    let caught: unknown = null;
    try {
      await transcribeAudio(blob);
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    const api = caught as ApiError;
    expect(api.status).toBe(415);
    expect(api.detail).toContain("Unsupported audio format");
  });
});
