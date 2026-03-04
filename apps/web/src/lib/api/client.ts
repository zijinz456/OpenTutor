/**
 * Core API client for OpenTutor backend.
 *
 * Simple fetch-based client. Phase 1 may upgrade to tRPC or orpc.
 */

import { buildAuthHeaders } from "@/lib/auth";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

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

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { headers, ...restOptions } = options ?? {};
  const res = await fetch(`${API_BASE}${path}`, {
    ...restOptions,
    headers: buildAuthHeaders({ "Content-Type": "application/json", ...headers }),
  });
  if (!res.ok) {
    throw await parseApiError(res);
  }
  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export { buildAuthHeaders };
