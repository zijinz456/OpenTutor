/**
 * Core API client for OpenTutor backend.
 *
 * Simple fetch-based client. Phase 1 may upgrade to tRPC or orpc.
 */

import { buildAuthHeaders } from "@/lib/auth";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export type JsonObject = Record<string, unknown>;
export type NullableDateTime = string | null;

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

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { headers, ...restOptions } = options ?? {};
  const res = await fetch(`${API_BASE}${path}`, {
    ...restOptions,
    headers: buildAuthHeaders({ "Content-Type": "application/json", ...headers }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error: ${res.status}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export { buildAuthHeaders };
