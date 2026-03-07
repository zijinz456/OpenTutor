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
  course_id?: string | null;
  action_url?: string | null;
  action_label?: string | null;
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

function notificationMatchesTask(notification: AppNotification, taskId: string): boolean {
  const data = notification.data;
  if (!data || typeof data !== "object") return false;
  const record = data as Record<string, unknown>;
  return record.task_id === taskId ||
    record.queued_task_id === taskId ||
    record.agent_task_id === taskId;
}

export async function markTaskNotificationsRead(taskId: string, limit = 100): Promise<void> {
  const { notifications } = await listNotifications({ limit });
  const targets = notifications.filter((n) => !n.read && notificationMatchesTask(n, taskId));
  if (targets.length === 0) return;
  await Promise.all(targets.map((n) => markNotificationRead(n.id)));
}
