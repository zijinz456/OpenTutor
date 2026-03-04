import { request } from "./client";

import type { JsonObject, NullableDateTime } from "./client";

// ── Preference Signals ──

interface PreferenceSignalContext {
  evidence?: string;
  user_message?: string;
}

export interface PreferenceSignal {
  id: string;
  dimension: string;
  value: string;
  signal_type: string;
  course_id: string | null;
  context: PreferenceSignalContext | null;
  created_at: NullableDateTime;
  dismissed_at?: string | null;
  dismissal_reason?: string | null;
}

export async function listPreferenceSignals(courseId?: string): Promise<PreferenceSignal[]> {
  const query = courseId ? `?course_id=${courseId}` : "";
  return request(`/preferences/signals${query}`);
}

// ── Learning Profile ──

interface LearningProfileSummary {
  strength_areas: string[];
  weak_areas: string[];
  recurring_errors: string[];
  inferred_habits: string[];
}

export interface Preference {
  id: string;
  dimension: string;
  value: string;
  scope: string;
  source: string;
  confidence: number;
  course_id: string | null;
  dismissed_at?: string | null;
  dismissal_reason?: string | null;
  updated_at: string;
}

export interface MemoryProfileItem {
  id: string;
  summary: string;
  memory_type: string;
  category: string | null;
  importance: number;
  access_count: number;
  source_message: string | null;
  metadata_json: JsonObject | null;
  created_at: NullableDateTime;
  updated_at: NullableDateTime;
  dismissed_at?: string | null;
  dismissal_reason?: string | null;
}

export interface LearningProfile {
  preferences: Preference[];
  dismissed_preferences: Preference[];
  signals: PreferenceSignal[];
  dismissed_signals: PreferenceSignal[];
  memories: MemoryProfileItem[];
  dismissed_memories: MemoryProfileItem[];
  summary: LearningProfileSummary;
}

export async function getLearningProfile(courseId?: string): Promise<LearningProfile> {
  const params = courseId ? `?course_id=${courseId}` : "";
  return request(`/preferences/profile${params}`);
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

// ── Dismiss / Restore ──

export async function dismissPreference(id: string, reason?: string): Promise<Preference> {
  return request(`/preferences/${id}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}

export async function restorePreference(id: string): Promise<Preference> {
  return request(`/preferences/${id}/restore`, { method: "POST" });
}

export async function dismissSignal(id: string, reason?: string): Promise<PreferenceSignal> {
  return request(`/preferences/signals/${id}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}

export async function restoreSignal(id: string): Promise<PreferenceSignal> {
  return request(`/preferences/signals/${id}/restore`, { method: "POST" });
}

export async function dismissMemory(id: string, reason?: string): Promise<MemoryProfileItem> {
  return request(`/preferences/memories/${id}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}

export async function restoreMemory(id: string): Promise<MemoryProfileItem> {
  return request(`/preferences/memories/${id}/restore`, { method: "POST" });
}

// ── LLM Runtime Config ──

interface LlmRuntimeProviderStatus {
  provider: string;
  has_key: boolean;
  masked_key: string | null;
  requires_key?: boolean;
}

export interface LlmRuntimeConfig {
  provider: string;
  model: string;
  llm_required: boolean;
  providers: LlmRuntimeProviderStatus[];
}

export interface LlmConnectionTestResult {
  provider: string;
  model: string;
  ok: boolean;
  response_preview: string;
  usage: Record<string, number>;
}

interface LlmRuntimeUpdateRequest {
  provider?: string;
  model?: string;
  llm_required?: boolean;
  provider_keys?: Record<string, string>;
  base_url?: string;
}

interface LlmRuntimeConnectionTestRequest {
  provider: string;
  model?: string;
  api_key?: string;
}

export async function getLlmRuntimeConfig(): Promise<LlmRuntimeConfig> {
  return request("/preferences/runtime/llm");
}

export async function updateLlmRuntimeConfig(body: LlmRuntimeUpdateRequest): Promise<LlmRuntimeConfig> {
  return request("/preferences/runtime/llm", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function testLlmRuntimeConnection(body: LlmRuntimeConnectionTestRequest): Promise<LlmConnectionTestResult> {
  return request("/preferences/runtime/llm/test", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ── Ollama ──

export interface OllamaModel {
  name: string;
  size: number;
  modified_at: string;
}

export async function getOllamaModels(baseUrl?: string): Promise<OllamaModel[]> {
  const params = baseUrl ? `?base_url=${encodeURIComponent(baseUrl)}` : "";
  return request(`/preferences/runtime/ollama/models${params}`);
}
