/**
 * Recursive URL crawler ingest — frontend client (§14.5 v2.5 T6).
 *
 * Backend contract: `POST /content/upload/url/recursive` (JSON body).
 *   - url:         seed URL (http/https)
 *   - course_id:   UUID of an existing course owned by the user
 *   - max_depth:   1 | 2 | 3 (backend enforces Literal)
 *   - path_prefix: optional tighter-than-origin filter
 *
 * Response: `RecursiveUrlResponse` — see `apps/api/routers/upload_url_recursive.py`.
 * Errors:
 *   - 400 invalid URL / invalid course_id
 *   - 404 course not found
 *   - 409 concurrent crawl already in progress for this course
 *   - 422 bad max_depth (outside Literal[1,2,3])
 *
 * We use direct `fetch` instead of the retrying `request` for the same
 * reason `uploadCoursera` does: retrying a crawl POST on 5xx would re-run
 * the BFS (minutes of work, re-dedups ingested pages), which is a much
 * worse failure mode than surfacing the error to the user once.
 */

import { API_BASE, ApiError, buildSecureRequestInit, parseApiError } from "./client";

export interface RecursiveUrlRequest {
  url: string;
  course_id: string;
  max_depth: 1 | 2 | 3;
  path_prefix?: string;
}

export interface RecursiveUrlResponse {
  course_id: string;
  pages_crawled: number;
  pages_skipped_robots: number;
  pages_skipped_origin: number;
  pages_skipped_dedup: number;
  pages_fetch_failed: number;
  job_ids: string[];
}

/** POST the crawl request to the recursive URL ingest endpoint. */
export async function uploadUrlRecursive(
  body: RecursiveUrlRequest,
): Promise<RecursiveUrlResponse> {
  const res = await fetch(`${API_BASE}/content/upload/url/recursive`, {
    ...buildSecureRequestInit({
      method: "POST",
      includeJsonContentType: true,
      body: JSON.stringify(body),
    }),
  });

  if (!res.ok) {
    throw await parseApiError(res);
  }
  return (await res.json()) as RecursiveUrlResponse;
}

/** Re-export `ApiError` so callers can `instanceof` without importing client. */
export { ApiError };
