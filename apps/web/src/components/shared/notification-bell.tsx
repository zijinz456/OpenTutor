"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Bell, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  listNotifications,
  markNotificationRead,
  type Notification,
} from "@/lib/api";
import { buildAuthHeaders } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export function NotificationBell() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    void (async () => {
      try {
        const data = await listNotifications(true, 50);
        if (active) {
          setNotifications(data);
        }
      } catch {
        // Silently ignore fetch errors
      }
    })();

    void (async () => {
      try {
        const res = await fetch(`${API_BASE}/notifications/stream`, {
          headers: buildAuthHeaders({ Accept: "text/event-stream" }),
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          return;
        }

        const decoder = new TextDecoder();
        let buffer = "";

        const processBlock = (block: string) => {
          let eventName = "message";
          const payload: string[] = [];
          for (const line of block.split(/\r?\n/)) {
            if (line.startsWith("event:")) {
              eventName = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              payload.push(line.slice(5).trim());
            }
          }
          if (eventName !== "notification" || payload.length === 0 || !active) {
            return;
          }
          try {
            const parsed = JSON.parse(payload.join("\n")) as Notification;
            setNotifications((prev) => {
              const next = [{ ...parsed, read: false }, ...prev.filter((item) => item.id !== parsed.id)];
              return next.slice(0, 50);
            });
          } catch {
            // Ignore malformed payloads.
          }
        };

        for await (const chunk of res.body as unknown as AsyncIterable<Uint8Array>) {
          buffer += decoder.decode(chunk, { stream: true });
          let boundary = buffer.search(/\r?\n\r?\n/);
          while (boundary !== -1) {
            processBlock(buffer.slice(0, boundary));
            const separatorMatch = buffer.slice(boundary).match(/^\r?\n\r?\n/);
            buffer = buffer.slice(boundary + (separatorMatch?.[0].length ?? 2));
            boundary = buffer.search(/\r?\n\r?\n/);
          }
        }
      } catch {
        // Ignore stream failures and keep the initial snapshot.
      }
    })();

    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
      return () =>
        document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [open]);

  const unreadCount = notifications.filter((n) => !n.read).length;

  async function handleMarkRead(id: string) {
    try {
      await markNotificationRead(id);
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, read: true } : n)),
      );
    } catch {
      // Silently ignore
    }
  }

  function handleAction(n: Notification) {
    if (n.action_url) {
      handleMarkRead(n.id);
      setOpen(false);
      router.push(n.action_url);
    }
  }

  return (
    <div ref={ref} className="relative">
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setOpen((v) => !v)}
        aria-label="Notifications"
        className="relative"
      >
        <Bell className="size-5" />
        {unreadCount > 0 && (
          <Badge
            variant="destructive"
            className="absolute -top-1 -right-1 flex size-5 items-center justify-center p-0 text-[10px]"
          >
            {unreadCount > 99 ? "99+" : unreadCount}
          </Badge>
        )}
      </Button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-80 rounded-lg border bg-popover p-2 shadow-lg">
          <p className="mb-2 px-2 text-sm font-semibold text-foreground">
            Notifications
          </p>
          {notifications.length === 0 ? (
            <p className="px-2 py-4 text-center text-sm text-muted-foreground">
              No new notifications
            </p>
          ) : (
            <ul className="max-h-80 space-y-1 overflow-y-auto">
              {notifications.map((n) => (
                <li key={n.id}>
                  <button
                    onClick={() => handleMarkRead(n.id)}
                    className={`w-full rounded-md px-2 py-2 text-left transition-colors hover:bg-accent ${
                      n.read ? "opacity-60" : ""
                    }`}
                  >
                    <div className="flex items-start justify-between gap-1">
                      <p className="text-sm font-medium leading-tight">
                        {n.title}
                      </p>
                      {n.priority === "high" || n.priority === "urgent" ? (
                        <span className="mt-0.5 inline-block size-2 shrink-0 rounded-full bg-red-500" />
                      ) : null}
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">
                      {n.body}
                    </p>
                    {n.action_url && n.action_label && (
                      <span
                        role="link"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleAction(n);
                        }}
                        className={`mt-1.5 inline-flex items-center gap-1 text-xs font-medium ${
                          n.priority === "high" || n.priority === "urgent"
                            ? "text-primary"
                            : "text-muted-foreground hover:text-foreground"
                        } cursor-pointer`}
                      >
                        {n.action_label}
                        <ArrowRight className="size-3" />
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
