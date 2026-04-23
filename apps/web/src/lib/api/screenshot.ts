/**
 * Screenshot-to-drill ingest adapter — frontend client (Phase 4 T4).
 *
 * Backend contract: `POST /api/content/upload/screenshot` (multipart form).
 *   - file:      UploadFile (PNG/JPEG/WebP, ≤5 MiB)
 *   - course_id: str (UUID of an existing course owned by the user)
 *
 * Response: `ScreenshotCandidatesResponse` — see `apps/api/schemas/screenshot.py`.
 * Errors:
 *   - 413 screenshot too large (>5 MiB)
 *   - 415 unsupported MIME (not PNG/JPEG/WebP)
 *   - 429 rate-limited (>5 screenshots / min per user)
 *   - 404 course not found / not owned
 *
 * We use a direct `fetch` (not the generic retrying `request`) for the same
 * reason Coursera's adapter does: auto-retrying a multipart POST would
 * re-upload the whole image on 5xx, which costs bandwidth and can
 * double-charge the vision-LLM call if the server partially succeeded.
 *
 * The save-candidates hop reuses the **existing** curriculum endpoint
 * `POST /api/courses/{id}/flashcards/save-candidates` with the new
 * optional `spawn_origin="screenshot"` flag. We remap the backend's
 * `{saved_problem_ids, count, ...}` shape into the prompt-contract
 * `{saved_count, problem_ids}` at this boundary so downstream components
 * (ScreenshotDropZone preview → saved toast) can stay slim.
 */

import { API_BASE, ApiError, buildSecureRequestInit, parseApiError } from "./client";

export interface CardCandidate {
  front: string;
  back: string;
  concept_slug?: string | null;
  screenshot_hash?: string | null;
}

export interface ScreenshotCandidatesResponse {
  candidates: CardCandidate[];
  screenshot_hash: string;
  vision_latency_ms: number;
  ungrounded_dropped_count: number;
}

/** Parsed `{reason, hint}` pulled out of the backend detail string. */
export interface ScreenshotErrorBody {
  detail: string;
  hint?: string;
}

/** Flattened save result — remap of the backend `SaveCandidatesResponse`. */
export interface ScreenshotSaveResult {
  saved_count: number;
  problem_ids: string[];
}

/** POST the image file to the screenshot ingest endpoint. */
export async function uploadScreenshot(
  courseId: string,
  file: File | Blob,
): Promise<ScreenshotCandidatesResponse> {
  const form = new FormData();
  // If caller passed a raw Blob we still want a filename field present
  // so FastAPI's UploadFile parser is happy.
  if (file instanceof File) {
    form.append("file", file);
  } else {
    form.append("file", file, "screenshot");
  }
  form.append("course_id", courseId);

  const res = await fetch(`${API_BASE}/content/upload/screenshot`, {
    ...buildSecureRequestInit({
      method: "POST",
      includeJsonContentType: false,
      body: form,
    }),
  });

  if (!res.ok) {
    throw await parseApiError(res);
  }
  return (await res.json()) as ScreenshotCandidatesResponse;
}

/**
 * Persist a batch of screenshot-origin candidates to the FSRS queue.
 *
 * Each card carries `screenshot_hash` so the audit trail survives into
 * `practice_problems.problem_metadata.screenshot_hash`; the batch-level
 * `spawn_origin="screenshot"` flag is what the backend uses to tag
 * `generated_assets.metadata_` and distinguish this flow from the
 * §14.5 chat-turn card-spawner path.
 */
export async function saveScreenshotCandidates(
  courseId: string,
  cards: CardCandidate[],
  screenshotHash: string,
): Promise<ScreenshotSaveResult> {
  // Tag every card with the screenshot_hash if the caller hasn't already.
  // Cheap and idempotent — backend is the source of truth for persistence
  // so a harmless double-write here never corrupts state.
  const candidates = cards.map((c) => ({
    ...c,
    screenshot_hash: c.screenshot_hash ?? screenshotHash,
  }));

  const res = await fetch(
    `${API_BASE}/courses/${courseId}/flashcards/save-candidates`,
    {
      ...buildSecureRequestInit({
        method: "POST",
        body: JSON.stringify({
          candidates,
          spawn_origin: "screenshot",
        }),
      }),
    },
  );

  if (!res.ok) {
    throw await parseApiError(res);
  }
  const body = (await res.json()) as {
    saved_problem_ids: string[];
    count: number;
  };
  return {
    saved_count: body.count,
    problem_ids: body.saved_problem_ids,
  };
}

/** Re-export `ApiError` so callers can `instanceof` without importing client. */
export { ApiError };
