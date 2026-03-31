import { API_BASE, buildSecureHeaders, buildSecureRequestInit, parseApiError, request } from "./client";

import type { ContentMutationResult, SavedGeneratedAsset } from "./client";
import type { GeneratedAssetBatchSummary } from "./practice";
import type { SpaceLayout } from "@/lib/block-system/types";

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
  layout?: Record<string, unknown> | null;
  spaceLayout?: SpaceLayout | Record<string, unknown> | null;
  learning_mode?: string | null;
  [key: string]: unknown;
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
  database_backend?: string;
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
  features?: Record<string, boolean>;
  local_beta_ready?: boolean;
  local_beta_blockers?: string[];
  local_beta_warnings?: string[];
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

export async function updateCourseLayout(
  courseId: string,
  layout: SpaceLayout | Record<string, unknown>,
): Promise<{ status: string; layout: Record<string, unknown> }> {
  return request(`/courses/${courseId}/layout`, {
    method: "PATCH",
    body: JSON.stringify(layout),
  });
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
  content_category?: "lecture_slides" | "textbook" | "notes" | "syllabus" | "assignment" | "exam_schedule" | "other" | null;
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

export interface AiNoteForNode {
  id: string;
  title: string;
  markdown: string;
  format: string;
  auto_generated: boolean;
  version: number;
}

export async function getAiNoteForNode(
  courseId: string,
  nodeId: string,
): Promise<AiNoteForNode | null> {
  return request(`/notes/generated/${courseId}/by-node/${nodeId}`);
}

export async function uploadFile(
  courseId: string,
  file: File,
  onProgress?: (pct: number) => void,
): Promise<ContentMutationResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("course_id", courseId);

  // Use XHR when caller wants progress updates; fall back to fetch otherwise.
  if (onProgress) {
    return new Promise<ContentMutationResult>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE}/content/upload`);
      const headers = buildSecureHeaders("POST", undefined, false);
      headers.forEach((value, key) => {
        xhr.setRequestHeader(key, value);
      });
      xhr.withCredentials = true;
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch {
            reject(new Error("Invalid JSON in upload response"));
          }
        } else {
          let detail = `Upload failed (${xhr.status})`;
          try { detail = JSON.parse(xhr.responseText)?.detail ?? detail; } catch { /* non-JSON error body */ }
          reject(new Error(detail));
        }
      };
      xhr.onerror = () => reject(new Error("Network error during upload"));
      xhr.send(form);
    });
  }

  const res = await fetch(`${API_BASE}/content/upload`, {
    ...buildSecureRequestInit({
      method: "POST",
      includeJsonContentType: false,
      body: form,
    }),
  });
  if (!res.ok) {
    throw await parseApiError(res);
  }
  return res.json();
}

export async function scrapeUrl(courseId: string, url: string): Promise<ContentMutationResult> {
  const form = new FormData();
  form.append("url", url);
  form.append("course_id", courseId);

  const res = await fetch(`${API_BASE}/content/url`, {
    ...buildSecureRequestInit({
      method: "POST",
      includeJsonContentType: false,
      body: form,
    }),
  });
  if (!res.ok) {
    throw await parseApiError(res);
  }
  return res.json();
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
  // Use a dedicated long timeout (330s > backend 300s) instead of the
  // generic 30s apiClient timeout, and no retries (each retry opens a new
  // Chromium window on the backend).
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 330_000);
  try {
    const res = await fetch(`${API_BASE}/canvas/browser-login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ canvas_url: canvasUrl, timeout_seconds: 300 }),
      signal: controller.signal,
      credentials: "include",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({})) as { message?: string; detail?: string };
      throw new Error(body.message ?? body.detail ?? "Login failed");
    }
    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function fetchCanvasCourseInfo(
  canvasUrl: string,
): Promise<{ name: string | null; course_code?: string }> {
  return request("/canvas/course-info", {
    method: "POST",
    body: JSON.stringify({ canvas_url: canvasUrl }),
  });
}
