/**
 * Tests for the room-generation POST client (Phase 16b Bundle B).
 *
 * The SSE hook lives in ``hooks/use-room-generation-stream.ts`` — covered
 * separately. Here we only verify request shape + error mapping.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { generateRoom, isGenerateRoomError } from "./path-generation";
import type {
  GenerateRoomError,
  GenerateRoomRequest,
} from "./path-generation";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function sampleRequest(): GenerateRoomRequest {
  return {
    path_id: "p-1",
    course_id: "c-1",
    topic: "binary search",
    difficulty: "beginner",
    task_count: 5,
  };
}

describe("generateRoom", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    localStorage.clear();
    localStorage.setItem("access_token", "token-gen");
    document.cookie = "csrf_token=csrf-gen;path=/";
  });

  afterEach(() => {
    document.cookie = "csrf_token=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/";
  });

  it("returns {job_id, reused:false} on 202 ACCEPTED", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ job_id: "job-123", reused: false }, 202),
    );

    const result = await generateRoom(sampleRequest());

    expect(result).toEqual({ job_id: "job-123", reused: false });

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/paths/generate-room");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer token-gen");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-gen");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual(sampleRequest());
  });

  it("returns {reused:true, room_id, path_id} on 200 reused", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(
        { reused: true, room_id: "room-9", path_id: "p-1" },
        200,
      ),
    );

    const result = await generateRoom(sampleRequest());

    expect(result).toEqual({
      reused: true,
      room_id: "room-9",
      path_id: "p-1",
    });
  });

  it("throws GenerateRoomError {code:'topic_guard'} on 400 topic_guard", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: { error: "topic_guard" } }, 400),
    );

    await expect(generateRoom(sampleRequest())).rejects.toMatchObject({
      status: 400,
      code: "topic_guard",
    });
  });

  it("throws GenerateRoomError {code:'path_course_mismatch'} on 400 mismatch", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: { error: "path_course_mismatch" } }, 400),
    );

    await expect(generateRoom(sampleRequest())).rejects.toMatchObject({
      status: 400,
      code: "path_course_mismatch",
    });
  });

  it("throws GenerateRoomError {code:'not_found'} on 404", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: "missing" }, 404));

    let caught: unknown = null;
    try {
      await generateRoom(sampleRequest());
    } catch (err) {
      caught = err;
    }
    expect(isGenerateRoomError(caught)).toBe(true);
    const err = caught as GenerateRoomError;
    expect(err.status).toBe(404);
    expect(err.code).toBe("not_found");
  });

  it("throws GenerateRoomError {code:'daily_generation_cap_exceeded'} on 429", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(
        { detail: { error: "daily_generation_cap_exceeded" } },
        429,
      ),
    );

    await expect(generateRoom(sampleRequest())).rejects.toMatchObject({
      status: 429,
      code: "daily_generation_cap_exceeded",
    });
  });

  it("falls back to code:'unknown' for unrecognized 5xx", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: "boom" }, 500));

    await expect(generateRoom(sampleRequest())).rejects.toMatchObject({
      status: 500,
      code: "unknown",
      message: "boom",
    });
  });
});
