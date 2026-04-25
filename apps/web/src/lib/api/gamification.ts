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
  /**
   * XP needed to reach the next tier (0 when at the cap).
   * Phase 16c Bundle B — Subagent B added the field for the dashboard
   * level-ring card; backend (Subagent A) emits it on every payload.
   */
  xp_to_next_level: number;
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

/**
 * Badge catalog entry returned by `GET /api/gamification/badges`
 * (Phase 16c Bundle C — Subagent A backend, Subagent B frontend).
 *
 * Locked badges still surface `key/title/description/hint` so the UI
 * can render a muted preview tile without round-tripping a separate
 * "definition" endpoint. `unlocked_at` is `null` for locked badges
 * and ISO-8601 UTC for unlocked ones.
 */
export interface BadgeOut {
  key: string;
  title: string;
  description: string;
  hint: string;
  unlocked: boolean;
  unlocked_at: string | null;
}

/** Response shape for `GET /api/gamification/badges`. */
export interface BadgesResponse {
  unlocked: BadgeOut[];
  locked: BadgeOut[];
}

/**
 * `GET /api/gamification/badges` — full badge catalog split into
 * unlocked / locked buckets. Same passive-fetch posture as
 * `getGamificationDashboard`: bypass the global toast wrapper so a
 * transient 5xx renders inline instead of firing a global error.
 */
export async function getBadges(): Promise<BadgesResponse> {
  const init = buildSecureRequestInit({ method: "GET" });
  const res = await fetch(`${API_BASE}/gamification/badges`, init);

  if (res.ok) {
    return (await res.json()) as BadgesResponse;
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
