import { API_BASE, request, requestBlob } from "./client";

// ── Usage ──

export interface UsageSummary {
  period: string;
  total_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  total_tool_calls: number;
}

export async function getUsageSummary(
  period: string = "month",
  courseId?: string,
): Promise<UsageSummary> {
  const params = new URLSearchParams({ period });
  if (courseId) params.set("course_id", courseId);
  return request(`/usage/summary?${params}`);
}

// ── Export ──

export async function downloadExportSession(courseId?: string) {
  const params = courseId ? `?course_id=${courseId}` : "";
  return requestBlob(`/export/session${params}`);
}

export function getAnkiExportUrl(courseId: string, batchId?: string): string {
  let url = `${API_BASE}/export/anki?course_id=${courseId}`;
  if (batchId) url += `&batch_id=${batchId}`;
  return url;
}

export function getCalendarExportUrl(
  courseId: string,
  planBatchId?: string
): string {
  let url = `${API_BASE}/export/calendar?course_id=${courseId}`;
  if (planBatchId) url += `&plan_batch_id=${planBatchId}`;
  return url;
}
