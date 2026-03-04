import { request } from "./client";

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
