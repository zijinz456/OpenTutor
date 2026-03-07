/**
 * Notifications API client.
 */

import { request } from "./client";

export interface AppNotification {
  id: string;
  title: string;
  body: string;
  category: string;
  read: boolean;
  data: Record<string, unknown> | null;
  created_at: string | null;
}

export interface NotificationsResponse {
  unread_count: number;
  notifications: AppNotification[];
}

export async function listNotifications(
  opts: { unreadOnly?: boolean; limit?: number } = {},
): Promise<NotificationsResponse> {
  const params = new URLSearchParams();
  if (opts.unreadOnly) params.set("unread_only", "true");
  if (opts.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return request<NotificationsResponse>(`/notifications${qs ? `?${qs}` : ""}`);
}

export async function markNotificationRead(id: string): Promise<void> {
  await request<{ ok: boolean }>(`/notifications/${id}/read`, { method: "POST" });
}

export async function markAllNotificationsRead(): Promise<void> {
  await request<{ ok: boolean }>("/notifications/read-all", { method: "POST" });
}
