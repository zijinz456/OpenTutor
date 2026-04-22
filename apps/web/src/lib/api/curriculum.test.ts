import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getCourseRoadmap,
  getCardCandidates,
  saveCardCandidates,
} from "./curriculum";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("curriculum API", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    localStorage.clear();
  });

  afterEach(() => {
    document.cookie = "csrf_token=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/";
  });

  it("getCourseRoadmap hits the expected URL and returns the list", async () => {
    const payload = [
      {
        node_id: "n1",
        slug: "intro",
        topic: "Intro",
        blurb: "b",
        mastery_score: 0.25,
        position: 0,
      },
    ];
    mockFetch.mockResolvedValueOnce(jsonResponse(payload));

    const result = await getCourseRoadmap("course-1");

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/courses\/course-1\/roadmap$/);
    expect(result).toEqual(payload);
  });

  it("getCardCandidates hits the nested sessions URL", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ cards: [] }));

    await getCardCandidates("sess-1", "msg-1");

    const [url] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(
      /\/courses\/sessions\/sess-1\/messages\/msg-1\/card-candidates$/,
    );
  });

  it("saveCardCandidates POSTs the candidate batch", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        saved_problem_ids: ["p1"],
        asset_id: "a1",
        count: 1,
        warnings: [],
      }),
    );
    const candidates = [
      { front: "F", back: "B", concept_slug: "intro" },
    ];

    await saveCardCandidates("course-1", candidates);

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/courses\/course-1\/flashcards\/save-candidates$/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ candidates });
  });
});
