/**
 * Path room-generation client (Phase 16b Bundle B).
 *
 * Thin wrapper over the two endpoints shipped under
 * ``/api/paths/generate-room`` in ``apps/api/routers/paths.py``:
 *
 *   POST /paths/generate-room                       → 202 {job_id, reused:false}
 *                                                  | 200 {reused:true, room_id, path_id}
 *   GET  /paths/generate-room/stream/{job_id}      → SSE (consumed by hook)
 *
 * Errors are flattened into a `GenerateRoomError` with a stable ``code`` so
 * callers can branch on intent (topic_guard, daily cap, …) rather than HTTP
 * status. The SSE side lives in ``hooks/use-room-generation-stream.ts`` —
 * `EventSource` cannot route through this client, so we keep this file
 * purely about the POST.
 *
 * NOTE: deliberately uses raw `fetch` (with shared auth/CSRF helpers) instead
 * of the retry/toast `request()` wrapper. Generation is non-idempotent
 * (the `reused` toggle relies on the server seeing exactly one POST per
 * user click), and we want to surface the typed error to the modal rather
 * than fire a global toast.
 */
import { API_BASE, buildSecureRequestInit } from "./client";

export type GenerateRoomDifficulty = "beginner" | "intermediate" | "advanced";

export interface GenerateRoomRequest {
  path_id: string;
  course_id: string;
  topic: string;
  difficulty: GenerateRoomDifficulty;
  task_count: number;
}

export interface GenerateRoomAccepted {
  job_id: string;
  reused: false;
}

export interface GenerateRoomReused {
  reused: true;
  room_id: string;
  path_id: string;
}

export type GenerateRoomResponse = GenerateRoomAccepted | GenerateRoomReused;

export type GenerateRoomErrorCode =
  | "topic_guard"
  | "path_course_mismatch"
  | "daily_generation_cap_exceeded"
  | "not_found"
  | "unknown";

export interface GenerateRoomError {
  status: number;
  code: GenerateRoomErrorCode;
  message: string;
}

/** True if the thrown value is shaped like a `GenerateRoomError`. */
export function isGenerateRoomError(err: unknown): err is GenerateRoomError {
  return (
    typeof err === "object" &&
    err !== null &&
    "code" in err &&
    "status" in err &&
    typeof (err as { status: unknown }).status === "number"
  );
}

interface ErrorBodyShape {
  detail?: string | { error?: string; [key: string]: unknown };
  [key: string]: unknown;
}

function mapErrorCode(
  status: number,
  detail: ErrorBodyShape["detail"],
): GenerateRoomErrorCode {
  if (typeof detail === "object" && detail !== null && typeof detail.error === "string") {
    const tag = detail.error;
    if (
      tag === "topic_guard" ||
      tag === "path_course_mismatch" ||
      tag === "daily_generation_cap_exceeded"
    ) {
      return tag;
    }
  }
  if (status === 404) return "not_found";
  if (status === 429) return "daily_generation_cap_exceeded";
  return "unknown";
}

function describeError(
  detail: ErrorBodyShape["detail"],
  fallback: string,
): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  return fallback;
}

/**
 * `POST /api/paths/generate-room` — schedule (or reuse) a generated room.
 *
 * Resolves to either the 202 `{job_id, reused:false}` shape (caller should
 * subscribe to the SSE stream) or the 200 `{reused:true, room_id, path_id}`
 * shape (server returned a recent identical room — caller routes straight
 * to it). Throws a typed `GenerateRoomError` for any non-2xx.
 */
export async function generateRoom(
  req: GenerateRoomRequest,
): Promise<GenerateRoomResponse> {
  const init = buildSecureRequestInit({
    method: "POST",
    body: JSON.stringify(req),
  });
  const res = await fetch(`${API_BASE}/paths/generate-room`, init);

  if (res.ok) {
    return (await res.json()) as GenerateRoomResponse;
  }

  let body: ErrorBodyShape = {};
  try {
    body = (await res.json()) as ErrorBodyShape;
  } catch {
    // Response had no JSON body — keep default {}.
  }
  const detail = body.detail;
  const fallbackMessage = res.statusText || `HTTP ${res.status}`;
  const code = mapErrorCode(res.status, detail);
  const message = describeError(detail, fallbackMessage);

  const err: GenerateRoomError = { status: res.status, code, message };
  throw err;
}
