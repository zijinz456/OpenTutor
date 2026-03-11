/**
 * API client for the onboarding interview endpoint.
 */

import { request } from "./client";

export interface OnboardingRequest {
  message: string;
  history: Array<{ role: string; content: string }>;
  partial_profile?: Record<string, unknown> | null;
}

export interface OnboardingAction {
  type: string;
  layout?: SpaceLayoutResponse;
  profile_summary?: {
    style: string;
    pattern: string;
    duration: string;
  };
}

export interface SpaceLayoutResponse {
  templateId: string;
  blocks: Array<{
    type: string;
    size: string;
    config: Record<string, unknown>;
    position: number;
    visible: boolean;
    source: string;
  }>;
  columns: number;
  mode: string;
}

export interface OnboardingResponse {
  response: string;
  actions: OnboardingAction[];
  profile: Record<string, unknown> | null;
  complete: boolean;
}

export interface DemoCourseResponse {
  id: string;
  name: string;
}

export async function getDemoCourse(): Promise<DemoCourseResponse> {
  return request<DemoCourseResponse>("/onboarding/demo-course");
}

export async function interviewTurn(body: OnboardingRequest): Promise<OnboardingResponse> {
  return request<OnboardingResponse>("/onboarding/interview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
