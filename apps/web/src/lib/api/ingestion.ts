import { API_BASE, request } from "./client";

import type { NullableDateTime } from "./client";

// ── Ingestion Jobs ──

export interface IngestionJobSummary {
  id: string;
  filename: string;
  source_type: string;
  category: string | null;
  status: string;
  phase_label: string | null;
  progress_percent: number;
  nodes_created: number;
  embedding_status: "pending" | "running" | "completed" | "failed";
  error_message: string | null;
  dispatched_to: Record<string, number> | null;
  created_at: NullableDateTime;
  updated_at: NullableDateTime;
}

export async function listIngestionJobs(courseId: string): Promise<IngestionJobSummary[]> {
  return request(`/content/jobs/${courseId}`);
}

// ── Scrape Sources ──

export interface ScrapeSource {
  id: string;
  url: string;
  label: string | null;
  course_id: string;
  source_type: string;
  requires_auth: boolean;
  auth_domain: string | null;
  session_name: string | null;
  enabled: boolean;
  interval_hours: number;
  last_scraped_at: string | null;
  last_status: string | null;
  last_content_hash: string | null;
  consecutive_failures: number;
  created_at: string;
}

// ── Course Sync ──

export interface SyncResult {
  status: string;
  new_files: number;
  updated_files: number;
  unchanged_files: number;
  files_discovered: number;
  job_id: string;
  job_status: string;
  nodes_created: number;
  content_changed: boolean;
}

export async function syncCourse(courseId: string): Promise<SyncResult> {
  return request(`/courses/${courseId}/sync`, { method: "POST" });
}

// ── Scrape Sources ──

export async function createScrapeSource(body: {
  course_id: string;
  url: string;
  label?: string;
  source_type?: "generic" | "canvas";
  requires_auth?: boolean;
  auth_domain?: string;
  session_name?: string;
  interval_hours?: number;
}): Promise<ScrapeSource> {
  return request("/scrape/sources", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function listScrapeSources(courseId: string): Promise<ScrapeSource[]> {
  return request(`/scrape/sources?course_id=${courseId}`);
}

export async function updateScrapeSource(
  sourceId: string,
  body: { enabled?: boolean; interval_hours?: number; label?: string },
): Promise<ScrapeSource> {
  return request(`/scrape/sources/${sourceId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteScrapeSource(sourceId: string): Promise<void> {
  return request(`/scrape/sources/${sourceId}`, { method: "DELETE" });
}

export async function scrapeNow(sourceId: string): Promise<{ status: string; content_changed: boolean; last_status: string }> {
  // Full browser-based scrape can take well over 30s for large Canvas courses.
  // Use a dedicated 120s timeout and bypass apiClient auto-retry (each retry
  // would trigger a redundant full scrape).
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120_000);
  try {
    const res = await fetch(`${API_BASE}/scrape/sources/${sourceId}/scrape-now`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      credentials: "include",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({})) as { message?: string; detail?: string };
      throw new Error(body.message ?? body.detail ?? `Scrape failed (${res.status})`);
    }
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}
