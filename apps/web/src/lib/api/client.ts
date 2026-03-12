/**
 * Core API client for OpenTutor backend.
 *
 * Simple fetch-based client. Phase 1 may upgrade to tRPC or orpc.
 */

import { toast } from "sonner";
import { buildAuthHeaders } from "@/lib/auth";

// In the browser, always use relative "/api" so requests go through the
// Next.js rewrite (same origin, avoids CSP connect-src issues).
// On the server (SSR), use NEXT_PUBLIC_API_URL to reach the backend directly.
export const API_BASE =
  typeof window !== "undefined"
    ? "/api"
    : process.env.NEXT_PUBLIC_API_URL || "/api";

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

function buildRequestHeaders(
  method: string,
  headers?: HeadersInit,
  includeJsonContentType: boolean = true,
): Headers {
  const csrfHeaders: Record<string, string> = {};
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrfToken = getCsrfToken();
    if (csrfToken) {
      csrfHeaders["X-CSRF-Token"] = csrfToken;
    }
  }
  const merged = new Headers();
  if (includeJsonContentType) {
    merged.set("Content-Type", "application/json");
  }
  for (const [key, value] of Object.entries(csrfHeaders)) {
    merged.set(key, value);
  }
  if (headers) {
    const incoming = new Headers(headers);
    incoming.forEach((value, key) => merged.set(key, value));
  }
  return buildAuthHeaders(merged);
}

export interface SecureRequestOptions extends Omit<RequestInit, "headers"> {
  headers?: HeadersInit;
  includeJsonContentType?: boolean;
}

export function buildSecureHeaders(
  method: string,
  headers?: HeadersInit,
  includeJsonContentType: boolean = true,
): Headers {
  return buildRequestHeaders(method.toUpperCase(), headers, includeJsonContentType);
}

export function buildSecureRequestInit(options?: SecureRequestOptions): RequestInit {
  const {
    method = "GET",
    headers,
    includeJsonContentType = true,
    credentials = "include",
    ...rest
  } = options ?? {};
  const normalizedMethod = method.toUpperCase();
  return {
    ...rest,
    method: normalizedMethod,
    credentials,
    headers: buildSecureHeaders(normalizedMethod, headers, includeJsonContentType),
  };
}

function parseFilenameFromDisposition(contentDisposition: string | null): string | null {
  if (!contentDisposition) return null;
  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }
  const simpleMatch = contentDisposition.match(/filename="?([^"]+)"?/i);
  return simpleMatch?.[1] ?? null;
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const fetchOptions = buildSecureRequestInit({
    ...(options ?? {}),
    includeJsonContentType: true,
  });

  let lastError: Error | undefined;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const res = await fetch(`${API_BASE}${path}`, {
        ...fetchOptions,
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
      // Network errors (fetch throws TypeError for network failures).
      // Only retry genuine network errors, not JSON.parse or other TypeErrors.
      if (
        err instanceof TypeError &&
        attempt < MAX_RETRIES &&
        (err.message.includes("fetch") || err.message.includes("network") || err.message === "Failed to fetch" || err.message.includes("NetworkError"))
      ) {
        lastError = err;
        await new Promise((r) => setTimeout(r, RETRY_BASE_MS * 2 ** attempt));
        continue;
      }
      throw err;
    }
  }

  throw lastError!;
}

export interface BinaryResponse {
  blob: Blob;
  fileName: string | null;
  contentType: string;
}

export async function requestBlob(path: string, options?: RequestInit): Promise<BinaryResponse> {
  const fetchOptions = buildSecureRequestInit({
    ...(options ?? {}),
    includeJsonContentType: false,
  });

  let lastError: Error | undefined;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const res = await fetch(`${API_BASE}${path}`, {
        ...fetchOptions,
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

      const blob = await res.blob();
      const fileName = parseFilenameFromDisposition(res.headers.get("Content-Disposition"));
      return {
        blob,
        fileName,
        contentType: res.headers.get("Content-Type") || "application/octet-stream",
      };
    } catch (err) {
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
