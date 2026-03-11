"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  listNotifications,
  markNotificationRead,
  markAllNotificationsRead,
  type AppNotification,
  type ChatAction,
} from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { useChatStore } from "@/store/chat";

const CHAT_ACTION_TYPES: ChatAction["action"][] = [
  "data_updated",
  "focus_topic",
  "add_block",
  "remove_block",
  "reorder_blocks",
  "resize_block",
  "apply_template",
  "agent_insight",
  "set_learning_mode",
  "suggest_mode",
];

function parseNotificationAction(
  data: AppNotification["data"],
): ChatAction | null {
  if (!data || typeof data.action !== "string") return null;
  const actionType = data.action.trim() as ChatAction["action"];
  if (!CHAT_ACTION_TYPES.includes(actionType)) return null;
  return {
    action: actionType,
    value: data.value != null ? String(data.value) : undefined,
    extra: data.extra != null ? String(data.extra) : undefined,
  };
}

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function NotificationBell() {
  const router = useRouter();
  const t = useT();
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  const fetchNotifications = useCallback(async () => {
    try {
      const data = await listNotifications({ limit: 20 });
      setNotifications(data.notifications);
      setUnreadCount(data.unread_count);
    } catch {
      // Silently fail — notifications are non-critical
    }
  }, []);

  // Poll every 60s + fetch on mount
  useEffect(() => {
    const kickoff = setTimeout(() => {
      void fetchNotifications();
    }, 0);
    const interval = setInterval(() => {
      void fetchNotifications();
    }, 60_000);
    return () => {
      clearTimeout(kickoff);
      clearInterval(interval);
    };
  }, [fetchNotifications]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const handleMarkRead = async (id: string) => {
    await markNotificationRead(id);
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: true } : n)),
    );
    setUnreadCount((c) => Math.max(0, c - 1));
  };

  const handleMarkAllRead = async () => {
    await markAllNotificationsRead();
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    setUnreadCount(0);
  };

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="ghost"
        size="icon-xs"
        className="text-muted-foreground hover:text-foreground"
        title={t("notification.title")}
        aria-label={t("notification.title")}
        aria-expanded={open ? "true" : "false"}
        aria-haspopup="true"
        onClick={() => setOpen((v) => !v)}
      >
        <Bell className="size-3.5" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex size-3.5 items-center justify-center rounded-full bg-destructive text-[9px] font-bold text-destructive-foreground">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </Button>

      {open && (
        <div role="region" aria-label="Notifications" className="absolute right-0 top-full mt-1 z-50 w-80 rounded-2xl bg-popover card-shadow animate-fade-in">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border/60">
            <span className="text-xs font-medium">{t("notification.title")}</span>
            {unreadCount > 0 && (
              <button
                type="button"
                aria-label="Mark all notifications as read"
                className="text-[10px] text-primary hover:underline"
                onClick={() => void handleMarkAllRead()}
              >
                {t("notification.markAllRead")}
              </button>
            )}
          </div>

          <div className="max-h-72 overflow-y-auto scrollbar-thin">
            {notifications.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                {t("notification.empty")}
              </div>
            ) : (
              notifications.map((n) => (
                <button
                  type="button"
                  key={n.id}
                  className={`w-full text-left px-3 py-2.5 border-b border-border/60 last:border-0 hover:bg-muted/50 transition-colors ${
                    !n.read ? "bg-primary/5" : ""
                  }`}
                  onClick={() => {
                    if (!n.read) void handleMarkRead(n.id);
                  }}
                >
                  <div className="flex items-start gap-2">
                    {!n.read && (
                      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium truncate">{n.title}</p>
                      <p className="text-[11px] text-muted-foreground line-clamp-2 mt-0.5">
                        {n.body}
                      </p>
                      <span className="text-[10px] text-muted-foreground/60 mt-0.5 block">
                        {timeAgo(n.created_at)}
                      </span>
                      {n.category === "insight" && !!n.data?.action && (
                        <button
                          type="button"
                          className="mt-1 text-[10px] font-medium text-primary hover:underline"
                          onClick={(e) => {
                            e.stopPropagation();
                            const action = parseNotificationAction(n.data);
                            if (action) useChatStore.getState().dispatchAction(action);
                            if (!n.read) void handleMarkRead(n.id);
                            setOpen(false);
                          }}
                        >
                          {t("notification.showInWorkspace")}
                        </button>
                      )}
                      {(n.action_url?.startsWith("/") || n.course_id) && (
                        <button
                          type="button"
                          className="mt-1 ml-2 text-[10px] font-medium text-primary hover:underline"
                          onClick={(e) => {
                            e.stopPropagation();
                            const path = n.action_url?.startsWith("/")
                              ? n.action_url
                              : n.course_id
                                ? `/course/${n.course_id}`
                                : null;
                            if (path) router.push(path);
                            if (!n.read) void handleMarkRead(n.id);
                            setOpen(false);
                          }}
                        >
                          {n.action_label || t("notification.open")}
                        </button>
                      )}
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
