"use client";

import { useEffect, useState } from "react";
import { Bell, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useNotificationStore } from "@/store/notifications";

const DISMISS_KEY = "opentutor_notif_dismiss";
const DISMISS_DAYS = 7;

function getDismissed(): boolean {
  if (typeof window === "undefined") return true;
  const raw = localStorage.getItem(DISMISS_KEY);
  if (!raw) return false;
  const ts = Number(raw);
  if (Number.isNaN(ts)) return false;
  return Date.now() - ts < DISMISS_DAYS * 86_400_000;
}

/**
 * Non-intrusive banner that asks the user to enable push notifications.
 * Shows once per course page visit unless dismissed (7-day cooldown)
 * or already subscribed.
 */
export function NotificationPrompt() {
  const { pushSupported, pushPermission, isSubscribed, subscribing, checkSubscription, subscribe } =
    useNotificationStore();
  const [dismissed, setDismissed] = useState(getDismissed);

  useEffect(() => {
    checkSubscription();
  }, [checkSubscription]);

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key === DISMISS_KEY) {
        setDismissed(getDismissed());
      }
    };
    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, []);

  const canShowPrompt = pushSupported && !isSubscribed && !dismissed && pushPermission !== "denied";
  if (!canShowPrompt) return null;

  const handleDismiss = () => {
    localStorage.setItem(DISMISS_KEY, String(Date.now()));
    setDismissed(true);
  };

  const handleEnable = async () => {
    await subscribe();
  };

  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-primary/5 border-b text-xs">
      <Bell className="h-3.5 w-3.5 text-primary shrink-0" />
      <span className="flex-1 text-foreground/80">
        Enable notifications to get flashcard review reminders at the right time.
      </span>
      <Button type="button" variant="default" size="sm" className="h-6 text-xs px-2" onClick={handleEnable} disabled={subscribing}>
        {subscribing ? "Enabling..." : "Enable"}
      </Button>
      <button type="button" onClick={handleDismiss} className="text-muted-foreground hover:text-foreground" title="Dismiss">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
