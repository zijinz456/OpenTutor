/**
 * Gamification dashboard client (Phase 16c Bundle C — Subagent A).
 *
 * Single read-only endpoint:
 *
 *   GET /api/gamification/dashboard → GamificationDashboard
 *
 * The endpoint always returns 200 with the full shape; for new accounts
 * counters are zero and arrays are empty. We use the shared
 * ``buildSecureRequestInit()`` so auth/CSRF parity matches the rest of
 * the API surface, but bypass the retry/toast ``request()`` wrapper:
 * gamification is a passive widget — a transient 5xx should bubble up to
 * the widget so it can render its own quiet fallback rather than firing
 * a global toast on dashboard load.
 */
import { API_BASE, buildSecureRequestInit } from "./client";

export type HeatmapTile = { date: string; xp: number };

export interface ActivePathSummary {
  path_id: string;
  slug: string;
  title: string;
  rooms_total: number;
  rooms_completed: number;
}

export interface GamificationDashboard {
  xp_total: number;
  level_tier: string;
  level_name: string;
  level_progress_pct: number;
  streak_days: number;
  streak_freezes_left: number;
  daily_goal_xp: number;
  daily_xp_earned: number;
  heatmap: HeatmapTile[];
  active_paths: ActivePathSummary[];
}

export interface GamificationApiError {
  status: number;
  message: string;
}

/** True if the thrown value is shaped like a `GamificationApiError`. */
export function isGamificationApiError(
  err: unknown,
): err is GamificationApiError {
  return (
    typeof err === "object" &&
    err !== null &&
    "status" in err &&
    typeof (err as { status: unknown }).status === "number" &&
    "message" in err
  );
}

interface ErrorBodyShape {
  detail?: unknown;
  message?: unknown;
}

function describeError(body: ErrorBodyShape, fallback: string): string {
  if (typeof body.detail === "string") return body.detail;
  if (typeof body.message === "string") return body.message;
  return fallback;
}

/** `GET /api/gamification/dashboard` — full snapshot for the widget. */
export async function getGamificationDashboard(): Promise<GamificationDashboard> {
  const init = buildSecureRequestInit({ method: "GET" });
  const res = await fetch(`${API_BASE}/gamification/dashboard`, init);

  if (res.ok) {
    return (await res.json()) as GamificationDashboard;
  }

  let body: ErrorBodyShape = {};
  try {
    body = (await res.json()) as ErrorBodyShape;
  } catch {
    // Response had no JSON body — keep default {}.
  }
  const fallback = res.statusText || `HTTP ${res.status}`;
  const err: GamificationApiError = {
    status: res.status,
    message: describeError(body, fallback),
  };
  throw err;
}
