"use client";

import { useEffect } from "react";
import { Bell, BellOff, AlertTriangle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { useNotificationStore } from "@/store/notifications";

export function PushSubscriptionManager() {
  const {
    pushSupported,
    pushPermission,
    isSubscribed,
    subscribing,
    error,
    checkSubscription,
    subscribe,
    unsubscribe,
  } = useNotificationStore();

  useEffect(() => {
    void checkSubscription();
  }, [checkSubscription]);

  const handleToggle = async () => {
    if (isSubscribed) {
      await unsubscribe();
      toast.success("Push notifications disabled");
    } else {
      await subscribe();
      const { pushPermission: perm, isSubscribed: sub } = useNotificationStore.getState();
      if (perm === "denied") {
        toast.error("Notification permission was denied. Please enable it in your browser settings.");
      } else if (sub) {
        toast.success("Push notifications enabled");
      }
    }
  };

  if (!pushSupported) {
    return (
      <div className="rounded-lg border p-4 space-y-2">
        <div className="flex items-center gap-2">
          <BellOff className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">Push Notifications</span>
          <Badge variant="secondary">Not supported</Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          Push notifications are not supported in this browser. Try using a modern browser like Chrome, Firefox, or Edge.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {isSubscribed ? (
            <Bell className="h-4 w-4" />
          ) : (
            <BellOff className="h-4 w-4 text-muted-foreground" />
          )}
          <span className="text-sm font-medium">Push Notifications</span>
          {isSubscribed && <Badge variant="default">Enabled</Badge>}
          {!isSubscribed && pushPermission === "denied" && (
            <Badge variant="destructive">Blocked</Badge>
          )}
        </div>
        <Button
          variant={isSubscribed ? "outline" : "default"}
          size="sm"
          onClick={() => void handleToggle()}
          disabled={subscribing || pushPermission === "denied"}
        >
          {subscribing ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {isSubscribed ? "Disabling..." : "Enabling..."}
            </>
          ) : isSubscribed ? (
            "Disable"
          ) : (
            "Enable"
          )}
        </Button>
      </div>

      <p className="text-sm text-muted-foreground">
        {isSubscribed
          ? "You will receive push notifications for study reminders, review schedules, and important updates."
          : "Enable push notifications to get study reminders, review alerts, and other proactive updates from OpenTutor."}
      </p>

      {pushPermission === "denied" && (
        <div className="flex items-start gap-2 rounded-md bg-destructive/10 px-3 py-2">
          <AlertTriangle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
          <p className="text-xs text-destructive">
            Notification permission is blocked. To enable push notifications, update your browser&apos;s site notification settings and reload this page.
          </p>
        </div>
      )}

      {error && !subscribing && (
        <p className="text-xs text-destructive">Error: {error}</p>
      )}
    </div>
  );
}
