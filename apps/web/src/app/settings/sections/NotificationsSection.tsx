"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type AppNotification,
} from "@/lib/api";
import { useT, useTF } from "@/lib/i18n-context";

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const deltaMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(deltaMs / 60_000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

export function NotificationsSection() {
  const t = useT();
  const tf = useTF();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const unreadCount = useMemo(
    () => notifications.reduce((count, item) => count + (item.read ? 0 : 1), 0),
    [notifications],
  );

  const loadNotifications = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listNotifications({ limit: 20 });
      setNotifications(result.notifications);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("settings.notificationsLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadNotifications();
  }, [loadNotifications]);

  const handleMarkAllRead = useCallback(async () => {
    if (unreadCount === 0) return;
    try {
      await markAllNotificationsRead();
      setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("settings.notificationsLoadFailed"));
    }
  }, [t, unreadCount]);

  const handleMarkRead = useCallback(async (id: string) => {
    try {
      await markNotificationRead(id);
      setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("settings.notificationsLoadFailed"));
    }
  }, [t]);

  return (
    <section data-testid="settings-notifications">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <h2 className="font-medium text-foreground">{t("settings.notifications")}</h2>
          <p className="text-sm text-muted-foreground">{t("settings.notificationsDescription")}</p>
        </div>
        {unreadCount > 0 ? (
          <Button variant="outline" size="sm" onClick={() => void handleMarkAllRead()}>
            {t("notification.markAllRead")}
          </Button>
        ) : null}
      </div>

      <p className="mb-3 text-xs text-muted-foreground">
        {tf("settings.notificationsUnreadCount", { count: unreadCount })}
      </p>

      {loading ? (
        <p className="text-sm text-muted-foreground">{t("general.loading")}</p>
      ) : null}

      {!loading && error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3">
          <p className="text-sm text-destructive">{error}</p>
          <Button className="mt-2" variant="outline" size="sm" onClick={() => void loadNotifications()}>
            {t("common.retry")}
          </Button>
        </div>
      ) : null}

      {!loading && !error && notifications.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("notification.empty")}</p>
      ) : null}

      {!loading && !error && notifications.length > 0 ? (
        <div className="space-y-2">
          {notifications.map((notification) => (
            <article
              key={notification.id}
              className={`rounded-md border p-3 ${
                notification.read ? "border-border bg-card" : "border-primary/40 bg-primary/5"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-medium text-foreground">
                    {notification.title}
                  </h3>
                  <p className="mt-1 text-xs text-muted-foreground">{notification.body}</p>
                </div>
                <span className="shrink-0 text-[11px] text-muted-foreground">
                  {timeAgo(notification.created_at)}
                </span>
              </div>
              {!notification.read ? (
                <Button
                  className="mt-2"
                  variant="outline"
                  size="sm"
                  onClick={() => void handleMarkRead(notification.id)}
                >
                  {t("settings.notificationsMarkRead")}
                </Button>
              ) : null}
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
