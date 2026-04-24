import { request } from "./client";

export interface ActiveFreeze {
  problem_id: string;
  expires_at: string;
}

export interface FreezeStatusResponse {
  quota_remaining: number;
  weekly_used: number;
  active_freezes: ActiveFreeze[];
}

export async function getFreezeStatus(): Promise<FreezeStatusResponse> {
  return request("/freeze/status");
}
