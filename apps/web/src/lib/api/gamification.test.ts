/**
 * Tests for the gamification dashboard client (Phase 16c Bundle C — Subagent A).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getGamificationDashboard,
  isGamificationApiError,
  type GamificationApiError,
  type GamificationDashboard,
} from "./gamification";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function fullDashboard(): GamificationDashboard {
  return {
    xp_total: 2450,
    level_tier: "Silver II",
    level_name: "Silver",
    level_progress_pct: 45,
    xp_to_next_level: 550,
    streak_days: 7,
    streak_freezes_left: 2,
    daily_goal_xp: 200,
    daily_xp_earned: 90,
    heatmap: [
      { date: "2026-04-01", xp: 30 },
      { date: "2026-04-02", xp: 50 },
    ],
    active_paths: [
      {
        path_id: "p-1",
        slug: "python-fundamentals",
        title: "Python Fundamentals",
        rooms_total: 10,
        rooms_completed: 4,
      },
    ],
  };
}

function emptyDashboard(): GamificationDashboard {
  return {
    xp_total: 0,
    level_tier: "Bronze I",
    level_name: "Bronze",
    level_progress_pct: 0,
    xp_to_next_level: 100,
    streak_days: 0,
    streak_freezes_left: 0,
    daily_goal_xp: 0,
    daily_xp_earned: 0,
    heatmap: [],
    active_paths: [],
  };
}

describe("getGamificationDashboard", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    localStorage.clear();
    localStorage.setItem("access_token", "token-gam");
    document.cookie = "csrf_token=csrf-gam;path=/";
  });

  afterEach(() => {
    document.cookie =
      "csrf_token=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/";
  });

  it("returns the dashboard shape on 200", async () => {
    const payload = fullDashboard();
    mockFetch.mockResolvedValueOnce(jsonResponse(payload, 200));

    const result = await getGamificationDashboard();

    expect(result).toEqual(payload);
    // Phase 16c Bundle B — xp_to_next_level must round-trip in the type.
    expect(result.xp_to_next_level).toBe(550);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/gamification/dashboard");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer token-gam");
  });

  it("parses an empty new-account response (zeros + empty arrays)", async () => {
    const payload = emptyDashboard();
    mockFetch.mockResolvedValueOnce(jsonResponse(payload, 200));

    const result = await getGamificationDashboard();

    expect(result.xp_total).toBe(0);
    expect(result.streak_days).toBe(0);
    expect(result.streak_freezes_left).toBe(0);
    expect(result.heatmap).toEqual([]);
    expect(result.active_paths).toEqual([]);
    // Phase 16c Bundle B — xp_to_next_level is non-zero even on empty
    // accounts (it represents the gap to the first promotion).
    expect(result.xp_to_next_level).toBe(100);
  });

  it("throws GamificationApiError preserving the HTTP status on non-2xx", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: "boom" }, 500));

    let caught: unknown = null;
    try {
      await getGamificationDashboard();
    } catch (err) {
      caught = err;
    }
    expect(isGamificationApiError(caught)).toBe(true);
    const err = caught as GamificationApiError;
    expect(err.status).toBe(500);
    expect(err.message).toBe("boom");
  });

  it("falls back to status text when the error body is not JSON", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response("not-json", {
        status: 503,
        statusText: "Service Unavailable",
      }),
    );

    await expect(getGamificationDashboard()).rejects.toMatchObject({
      status: 503,
      message: "Service Unavailable",
    });
  });
});
