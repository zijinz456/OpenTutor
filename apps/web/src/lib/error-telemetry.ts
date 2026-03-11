import { ApiError } from "@/lib/api/client";

export type ApiErrorChannel = "graph" | "rating" | "download" | "voice";

interface ApiErrorTelemetryPayload {
  channel: ApiErrorChannel;
  message: string;
  endpoint?: string;
  courseId?: string;
  code?: string;
  status?: number;
  meta?: Record<string, unknown>;
  timestamp: string;
}

export function trackApiFailure(
  channel: ApiErrorChannel,
  error: unknown,
  context: {
    endpoint?: string;
    courseId?: string;
    meta?: Record<string, unknown>;
  } = {},
): void {
  const message = error instanceof Error ? error.message : String(error);
  const payload: ApiErrorTelemetryPayload = {
    channel,
    message,
    endpoint: context.endpoint,
    courseId: context.courseId,
    code: error instanceof ApiError ? error.code : undefined,
    status: error instanceof ApiError ? error.status : undefined,
    meta: context.meta,
    timestamp: new Date().toISOString(),
  };

  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("opentutor:api-error", { detail: payload }));
  }

  console.error(`[API:${channel}]`, payload);
}
