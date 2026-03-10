/**
 * Core API client for OpenTutor backend.
 *
 * Simple fetch-based client. Phase 1 may upgrade to tRPC or orpc.
 */

import { toast } from "sonner";
import { buildAuthHeaders } from "@/lib/auth";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

/** Show a toast for API errors (non-chat requests). */
function showApiErrorToast(err: ApiError): void {
  if (typeof window === "undefined") return;
  const description = err.status === 429
    ? "Rate limit reached. Please wait a moment."
    : err.status === 503
      ? "Service temporarily unavailable."
      : err.detail || err.message;
  toast.error("Request failed", { description, duration: 5000 });
}

export type JsonObject = Record<string, unknown>;
export type NullableDateTime = string | null;

export class ApiError extends Error {
  status: number;
  code?: string;
  detail?: string;

  constructor(message: string, options: { status: number; code?: string; detail?: string }) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.detail = options.detail;
  }
}

export interface VersionedBatch {
  batch_id: string;
  version: number;
  replaced: boolean;
}

export interface SavedGeneratedAsset extends VersionedBatch {
  id: string;
}

export interface ContentMutationResult {
  nodes_created: number;
}

export interface GeneratedBatchSummaryBase {
  batch_id: string;
  title: string;
  current_version: number;
  is_active: boolean;
  updated_at: NullableDateTime;
}

export async function parseApiError(res: Response): Promise<ApiError> {
  const fallbackDetail = res.statusText || `API error: ${res.status}`;
  const payload = await res.json().catch(() => null) as
    | { detail?: string; message?: string; code?: string }
    | null;
  const detail = payload?.detail || payload?.message || fallbackDetail;

  return new ApiError(detail, {
    status: res.status,
    code: payload?.code,
    detail,
  });
}

const MAX_RETRIES = 3;
const RETRY_BASE_MS = 1000;

function isRetryable(status: number): boolean {
  return status >= 500 || status === 429;
}

function getCsrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match?.[1];
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { headers, ...restOptions } = options ?? {};
  const csrfHeaders: Record<string, string> = {};
  const method = (restOptions.method || "GET").toUpperCase();
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrfToken = getCsrfToken();
    if (csrfToken) {
      csrfHeaders["X-CSRF-Token"] = csrfToken;
    }
  }
  const mergedHeaders = buildAuthHeaders({
    "Content-Type": "application/json",
    ...csrfHeaders,
    ...headers,
  });

  let lastError: Error | undefined;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const res = await fetch(`${API_BASE}${path}`, {
        ...restOptions,
        credentials: "include",
        headers: mergedHeaders,
      });

      if (!res.ok) {
        const err = await parseApiError(res);
        if (attempt < MAX_RETRIES && isRetryable(res.status)) {
          lastError = err;
          await new Promise((r) => setTimeout(r, RETRY_BASE_MS * 2 ** attempt));
          continue;
        }
        showApiErrorToast(err);
        throw err;
      }

      if (res.status === 204) {
        return undefined as T;
      }

      const text = await res.text();
      return text ? (JSON.parse(text) as T) : (undefined as T);
    } catch (err) {
      // Network errors (fetch throws TypeError for network failures)
      if (err instanceof TypeError && attempt < MAX_RETRIES) {
        lastError = err;
        await new Promise((r) => setTimeout(r, RETRY_BASE_MS * 2 ** attempt));
        continue;
      }
      throw err;
    }
  }

  throw lastError!;
}

export { buildAuthHeaders };
