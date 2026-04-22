/**
 * Coursera ZIP ingest adapter — frontend client.
 *
 * Backend contract: `POST /content/upload/coursera` (multipart form).
 *   - file:      UploadFile (.zip)
 *   - course_id: str (UUID of an existing course owned by the user)
 *
 * Response: `CourseraUploadResponse` — see `apps/api/schemas/coursera.py`.
 * Errors:
 *   - 400 ValidationError    → detail contains "<reason>. Hint: <hint>"
 *   - 404 course not found
 *   - 413-ish: size cap rejected with 400 detail "ZIP too large..."
 *
 * We use a direct `fetch` (not the generic retrying `request`) for the same
 * reason `scrapeUrl` / `uploadFile` do: auto-retrying a multipart POST would
 * re-upload the whole ZIP on 5xx, which costs bandwidth and can create
 * duplicate IngestionJobs if the server partially succeeded.
 */

import { API_BASE, ApiError, buildSecureRequestInit, parseApiError } from "./client";

export interface CourseraUploadResponse {
  course_id: string;
  lectures_total: number;
  lectures_paired: number;
  lectures_vtt_only: number;
  lectures_pdf_only: number;
  job_ids: string[];
  status: "created" | "already_imported";
}

/** Parsed `{reason, hint}` pulled out of the backend 400 detail string. */
export interface CourseraErrorBody {
  detail: string;
  reason?: string;
  hint?: string;
}

/**
 * Parse the 400 detail "Coursera ZIP rejected: <reason>. Hint: <hint>"
 * into structured `{reason, hint}`. Falls back to the raw detail if the
 * shape doesn't match — we'd rather show *something* than swallow the
 * error.
 */
export function parseCourseraErrorDetail(detail: string): CourseraErrorBody {
  const match = detail.match(/^Coursera ZIP rejected:\s*(.+?)\.\s*Hint:\s*(.+)$/);
  if (match) {
    return { detail, reason: match[1].trim(), hint: match[2].trim() };
  }
  return { detail };
}

/** POST the ZIP file to the Coursera ingest endpoint. */
export async function uploadCoursera(
  courseId: string,
  file: File,
): Promise<CourseraUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("course_id", courseId);

  const res = await fetch(`${API_BASE}/content/upload/coursera`, {
    ...buildSecureRequestInit({
      method: "POST",
      includeJsonContentType: false,
      body: form,
    }),
  });

  if (!res.ok) {
    throw await parseApiError(res);
  }
  return (await res.json()) as CourseraUploadResponse;
}

/** Re-export `ApiError` so callers can `instanceof` without importing client. */
export { ApiError };
