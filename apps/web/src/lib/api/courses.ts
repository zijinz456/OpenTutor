import { buildAuthHeaders } from "@/lib/auth";

import { API_BASE, request } from "./client";

import type { ContentMutationResult, SavedGeneratedAsset } from "./client";
import type { GeneratedAssetBatchSummary } from "./practice";

// ── Courses ──

export interface CourseWorkspaceFeatures {
  notes: boolean;
  practice: boolean;
  wrong_answer: boolean;
  study_plan: boolean;
  free_qa: boolean;
}

export interface CourseAutoScrapeSettings {
  enabled: boolean;
  interval_hours: number;
}

export interface CourseMetadata {
  workspace_features?: Partial<CourseWorkspaceFeatures> | null;
  auto_scrape?: CourseAutoScrapeSettings | null;
}

export interface Course {
  id: string;
  name: string;
  description: string | null;
  metadata?: CourseMetadata | null;
  created_at: string;
  updated_at?: string | null;
  file_count?: number;
  content_node_count?: number;
  active_goal_count?: number;
  pending_task_count?: number;
  pending_approval_count?: number;
  last_agent_activity_at?: string | null;
  last_scene_id?: string | null;
}

export interface CourseOverviewCard extends Course {
  updated_at: string | null;
  file_count: number;
  content_node_count: number;
  active_goal_count: number;
  pending_task_count: number;
  pending_approval_count: number;
  last_agent_activity_at: string | null;
  last_scene_id: string | null;
}

export interface HealthStatus {
  status: string;
  version: string;
  database: string;
  schema?: "ready" | "missing" | "unknown" | string;
  migration_required?: boolean;
  migration_status?: string;
  alembic_version_present?: boolean;
  migration_current_revisions?: string[];
  migration_expected_revisions?: string[];
  llm_providers: string[];
  llm_primary: string | null;
  llm_required: boolean;
  llm_available: boolean;
  llm_status: "configuration_required" | "mock_fallback" | "degraded" | "ready";
  llm_provider_health: Record<string, boolean>;
  deployment_mode: "single_user" | "multi_user" | string;
  auth_enabled?: boolean;
  code_sandbox_backend: string;
  code_sandbox_runtime: string;
  code_sandbox_runtime_available: boolean;
}

export async function listCourseOverview(): Promise<CourseOverviewCard[]> {
  return request("/courses/overview");
}

export async function getHealthStatus(): Promise<HealthStatus> {
  return request("/health");
}

export async function createCourse(
  name: string,
  description?: string,
  metadata?: CourseMetadata,
): Promise<Course> {
  return request("/courses/", {
    method: "POST",
    body: JSON.stringify({ name, description, metadata }),
  });
}

export async function updateCourse(
  courseId: string,
  payload: {
    name?: string;
    description?: string;
    metadata?: CourseMetadata;
  },
): Promise<Course> {
  return request(`/courses/${courseId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteCourse(id: string): Promise<void> {
  await request<void>(`/courses/${id}`, { method: "DELETE" });
}

// ── Content ──

export interface ContentNode {
  id: string;
  title: string;
  type: "week" | "topic" | "section" | "file" | string;
  content: string | null;
  level: number;
  order_index: number;
  source_type: string;
  children: ContentNode[];
  file_type?: string;
  file_id?: string;
}

export async function getContentTree(courseId: string): Promise<ContentNode[]> {
  return request(`/courses/${courseId}/content-tree`);
}

export interface RestructuredNotes {
  original_title: string;
  ai_content: string;
  format_used: string;
}

export async function restructureNotes(
  contentNodeId: string,
  formatOverride?: string,
): Promise<RestructuredNotes> {
  return request("/notes/restructure", {
    method: "POST",
    body: JSON.stringify({
      content_node_id: contentNodeId,
      format_override: formatOverride,
    }),
  });
}

export async function saveGeneratedNotes(
  courseId: string,
  markdown: string,
  title: string,
  sourceNodeId?: string,
  replaceBatchId?: string,
): Promise<SavedGeneratedAsset> {
  return request("/notes/generated/save", {
    method: "POST",
    body: JSON.stringify({
      course_id: courseId,
      markdown,
      title,
      source_node_id: sourceNodeId,
      replace_batch_id: replaceBatchId,
    }),
  });
}

export async function listGeneratedNoteBatches(courseId: string): Promise<GeneratedAssetBatchSummary[]> {
  return request(`/notes/generated/${courseId}`);
}

export async function uploadFile(courseId: string, file: File): Promise<ContentMutationResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("course_id", courseId);

  const res = await fetch(`${API_BASE}/content/upload`, {
    method: "POST",
    headers: buildAuthHeaders(),
    body: form,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || error.message || "Upload failed");
  }
  return res.json();
}

export async function scrapeUrl(courseId: string, url: string): Promise<ContentMutationResult> {
  const form = new FormData();
  form.append("url", url);
  form.append("course_id", courseId);

  const res = await fetch(`${API_BASE}/content/url`, {
    method: "POST",
    headers: buildAuthHeaders(),
    body: form,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || error.message || "Scrape failed");
  }
  return res.json();
}

export function getFileUrl(jobId: string): string {
  return `${API_BASE}/content/files/${jobId}`;
}

// ── Canvas / Auth Sessions ──

export interface AuthSessionSummary {
  id: string;
  domain: string;
  session_name: string;
  auth_type: string;
  is_valid: boolean;
  last_validated_at: string | null;
}

export async function listAuthSessions(): Promise<AuthSessionSummary[]> {
  return request("/scrape/auth/sessions");
}

export async function canvasBrowserLogin(
  canvasUrl: string,
): Promise<{ status: string; message: string }> {
  return request("/canvas/browser-login", {
    method: "POST",
    body: JSON.stringify({ canvas_url: canvasUrl, timeout_seconds: 300 }),
  });
}
