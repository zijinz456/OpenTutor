import { request } from "./client";

// ── Push Notifications ──

interface PushSubscriptionRequest {
  endpoint: string;
  p256dh_key: string;
  auth_key: string;
  user_agent: string;
}

interface PushUnsubscribeRequest {
  endpoint: string;
}

interface VapidKeyResponse {
  public_key: string;
}

export async function getVapidKey(): Promise<VapidKeyResponse> {
  return request("/notifications/push/vapid-key");
}

export async function subscribePush(body: PushSubscriptionRequest): Promise<void> {
  return request("/notifications/push/subscribe", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function unsubscribePush(body: PushUnsubscribeRequest): Promise<void> {
  return request("/notifications/push/unsubscribe", {
    method: "DELETE",
    body: JSON.stringify(body),
  });
}

// ── Notifications ──

export interface Notification {
  id: string;
  user_id?: string;
  title: string;
  body: string;
  category: string;
  read: boolean;
  created_at: string;
  action_url?: string;
  action_label?: string;
  priority?: string;
  metadata_json?: Record<string, unknown>;
}

export async function listNotifications(
  unreadOnly = true,
  limit = 50,
): Promise<Notification[]> {
  return request(`/notifications/?unread_only=${unreadOnly}&limit=${limit}`);
}

export async function markNotificationRead(
  notificationId: string,
): Promise<void> {
  return request(`/notifications/${notificationId}/read`, { method: "POST" });
}

// ── Notification Settings ──

export interface NotificationSettings {
  id: string;
  user_id: string;
  channels_enabled: string[];
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  timezone: string;
  max_notifications_per_hour: number;
  max_notifications_per_day: number;
  preferred_study_time: string | null;
  study_time_confidence: number;
  escalation_enabled: boolean;
  escalation_delay_hours: number;
  created_at: string;
  updated_at: string;
}

interface NotificationSettingsUpdateRequest {
  channels_enabled?: string[];
  quiet_hours_start?: string | null;
  quiet_hours_end?: string | null;
  timezone?: string | null;
  max_notifications_per_hour?: number;
  max_notifications_per_day?: number;
  escalation_enabled?: boolean;
  escalation_delay_hours?: number;
}

export async function getNotificationSettings(): Promise<NotificationSettings> {
  return request("/notifications/settings");
}

export async function updateNotificationSettings(
  body: NotificationSettingsUpdateRequest,
): Promise<NotificationSettings> {
  return request("/notifications/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}
