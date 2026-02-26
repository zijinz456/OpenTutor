/**
 * API client for OpenTutor backend.
 *
 * Simple fetch-based client. Phase 1 may upgrade to tRPC or orpc.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error: ${res.status}`);
  }
  return res.json();
}

// ── Courses ──

export interface Course {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}

export async function listCourses(): Promise<Course[]> {
  return request("/courses/");
}

export async function createCourse(name: string, description?: string): Promise<Course> {
  return request("/courses/", {
    method: "POST",
    body: JSON.stringify({ name, description }),
  });
}

export async function deleteCourse(id: string): Promise<void> {
  await fetch(`${API_BASE}/courses/${id}`, { method: "DELETE" });
}

// ── Content ──

export interface ContentNode {
  id: string;
  title: string;
  content: string | null;
  level: number;
  order_index: number;
  source_type: string;
  children: ContentNode[];
}

export async function getContentTree(courseId: string): Promise<ContentNode[]> {
  return request(`/courses/${courseId}/content-tree`);
}

export async function uploadFile(courseId: string, file: File): Promise<{ nodes_created: number }> {
  const form = new FormData();
  form.append("file", file);
  form.append("course_id", courseId);

  const res = await fetch(`${API_BASE}/content/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || "Upload failed");
  }
  return res.json();
}

export async function scrapeUrl(courseId: string, url: string): Promise<{ nodes_created: number }> {
  const form = new FormData();
  form.append("url", url);
  form.append("course_id", courseId);

  const res = await fetch(`${API_BASE}/content/url`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || "Scrape failed");
  }
  return res.json();
}

// ── Chat (SSE streaming) ──

export interface ChatAction {
  action: string;
  value?: string;
  extra?: string;
}

export type StreamEvent =
  | { type: "content"; content: string }
  | { type: "action"; action: ChatAction };

export async function* streamChat(
  courseId: string,
  message: string,
): AsyncGenerator<StreamEvent, void, unknown> {
  const res = await fetch(`${API_BASE}/chat/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ course_id: courseId, message }),
  });

  if (!res.ok || !res.body) {
    throw new Error("Chat stream failed");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("event: ")) continue;
      if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6));
          if (data.content) {
            yield { type: "content", content: data.content };
          } else if (data.action) {
            yield { type: "action", action: data as ChatAction };
          }
        } catch {
          // skip non-JSON lines
        }
      }
    }
  }
}

// ── Preferences ──

export interface Preference {
  id: string;
  dimension: string;
  value: string;
  scope: string;
  source: string;
  confidence: number;
  course_id: string | null;
  updated_at: string;
}

export interface ResolvedPreferences {
  preferences: Record<string, string>;
  sources: Record<string, string>;
}

export async function listPreferences(): Promise<Preference[]> {
  return request("/preferences/");
}

export async function setPreference(
  dimension: string,
  value: string,
  scope: string = "global",
  courseId?: string,
  source: string = "onboarding",
): Promise<Preference> {
  return request("/preferences/", {
    method: "POST",
    body: JSON.stringify({
      dimension,
      value,
      scope,
      course_id: courseId,
      source,
    }),
  });
}

export async function resolvePreferences(courseId?: string): Promise<ResolvedPreferences> {
  const params = courseId ? `?course_id=${courseId}` : "";
  return request(`/preferences/resolve${params}`);
}
