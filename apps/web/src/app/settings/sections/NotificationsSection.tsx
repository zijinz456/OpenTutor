"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { useT } from "@/lib/i18n-context";
import {
  getNotificationSettings,
  updateNotificationSettings,
} from "@/lib/api";
import { useNotificationStore } from "@/store/notifications";
import type { NotificationSettings } from "./types";

export function NotificationsSection() {
  const t = useT();
  const {
    pushSupported,
    pushPermission,
    isSubscribed,
    subscribing: pushBusy,
    error: pushError,
    checkSubscription,
    subscribe,
    unsubscribe,
  } = useNotificationStore();

  const [notificationSettings, setNotificationSettings] =
    useState<NotificationSettings | null>(null);
  const [notificationLoading, setNotificationLoading] = useState(false);
  const [notificationSaving, setNotificationSaving] = useState(false);
  const [availableTimezones, setAvailableTimezones] = useState<string[]>(["UTC"]);
  const channelOptions = [
    { id: "sse", label: "In-app realtime" },
    { id: "web_push", label: "Browser push" },
    { id: "telegram", label: "Telegram" },
  ] as const;

  useEffect(() => {
    if (typeof Intl !== "undefined" && "supportedValuesOf" in Intl) {
      const zones = (Intl as typeof Intl & {
        supportedValuesOf?: (key: string) => string[];
      }).supportedValuesOf?.("timeZone");
      if (zones && zones.length > 0) {
        setAvailableTimezones(zones);
      }
    }
  }, []);

  useEffect(() => {
    void loadNotificationSettings();
    void checkSubscription();
  }, [checkSubscription]);

  async function loadNotificationSettings(): Promise<void> {
    setNotificationLoading(true);
    try {
      const data = await getNotificationSettings();
      setNotificationSettings(data);
    } catch {
      setNotificationSettings(null);
    } finally {
      setNotificationLoading(false);
    }
  }

  async function handleSaveNotifications(): Promise<void> {
    if (!notificationSettings) return;
    setNotificationSaving(true);
    try {
      const updated = await updateNotificationSettings({
        channels_enabled: notificationSettings.channels_enabled,
        quiet_hours_start: notificationSettings.quiet_hours_start,
        quiet_hours_end: notificationSettings.quiet_hours_end,
        timezone: notificationSettings.timezone,
        max_notifications_per_hour:
          notificationSettings.max_notifications_per_hour,
        max_notifications_per_day:
          notificationSettings.max_notifications_per_day,
        escalation_enabled: notificationSettings.escalation_enabled,
        escalation_delay_hours: notificationSettings.escalation_delay_hours,
      });
      setNotificationSettings(updated);
      toast.success("Notification settings saved");
    } catch (error) {
      toast.error(
        (error as Error).message || "Failed to save notification settings",
      );
    } finally {
      setNotificationSaving(false);
    }
  }

  function updateSetting<K extends keyof NotificationSettings>(
    key: K,
    value: NotificationSettings[K],
  ): void {
    setNotificationSettings((current) =>
      current ? { ...current, [key]: value } : current,
    );
  }

  function toggleChannel(channelId: typeof channelOptions[number]["id"]): void {
    setNotificationSettings((current) => {
      if (!current) return current;
      const enabled = current.channels_enabled.includes(channelId);
      return {
        ...current,
        channels_enabled: enabled
          ? current.channels_enabled.filter((value) => value !== channelId)
          : [...current.channels_enabled, channelId],
      };
    });
  }

  return (
    <section data-testid="settings-notifications">
      <h2 className="font-medium text-foreground mb-3">
        {t("settings.notifications")}
      </h2>
      <div className="rounded-xl border border-border p-4 space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">
            Push supported: {pushSupported ? "yes" : "no"}
          </Badge>
          <Badge variant="outline">
            Permission: {pushPermission || "unknown"}
          </Badge>
          <Badge variant={isSubscribed ? "secondary" : "outline"}>
            {isSubscribed ? "Subscribed" : "Not subscribed"}
          </Badge>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void checkSubscription()}
            disabled={pushBusy}
          >
            Refresh Browser Status
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={() => void subscribe()}
            disabled={!pushSupported || pushBusy || isSubscribed}
          >
            {pushBusy && !isSubscribed ? "Working..." : "Enable Push"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void unsubscribe()}
            disabled={!isSubscribed || pushBusy}
          >
            Disable Push
          </Button>
        </div>

        {pushError && (
          <p className="text-xs text-destructive">{pushError}</p>
        )}

        {notificationLoading ? (
          <div className="h-4 w-36 rounded bg-muted animate-pulse" />
        ) : notificationSettings ? (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2 text-sm">
              <span className="font-medium text-foreground">Channels</span>
              <div className="space-y-2 rounded-md border border-border p-3">
                {channelOptions.map((channel) => (
                  <label key={channel.id} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={notificationSettings.channels_enabled.includes(channel.id)}
                      onChange={() => toggleChannel(channel.id)}
                    />
                    <span className="text-sm text-foreground">{channel.label}</span>
                  </label>
                ))}
              </div>
              <span className="block text-xs text-muted-foreground">
                Leave all unchecked to save notifications without immediate delivery.
              </span>
            </div>

            <label className="space-y-2 text-sm">
              <span className="font-medium text-foreground">Timezone</span>
              <select
                value={notificationSettings.timezone}
                onChange={(e) => updateSetting("timezone", e.target.value)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                {Array.from(new Set([notificationSettings.timezone, ...availableTimezones]))
                  .sort()
                  .map((timezone) => (
                    <option key={timezone} value={timezone}>
                      {timezone}
                    </option>
                  ))}
              </select>
            </label>

            <label className="space-y-2 text-sm">
              <span className="font-medium text-foreground">
                Quiet hours start
              </span>
              <Input
                value={notificationSettings.quiet_hours_start || ""}
                onChange={(e) =>
                  updateSetting(
                    "quiet_hours_start",
                    e.target.value || null,
                  )
                }
                placeholder="22:00"
              />
            </label>

            <label className="space-y-2 text-sm">
              <span className="font-medium text-foreground">
                Quiet hours end
              </span>
              <Input
                value={notificationSettings.quiet_hours_end || ""}
                onChange={(e) =>
                  updateSetting(
                    "quiet_hours_end",
                    e.target.value || null,
                  )
                }
                placeholder="07:00"
              />
            </label>

            <label className="space-y-2 text-sm">
              <span className="font-medium text-foreground">
                Max notifications / hour
              </span>
              <Input
                type="number"
                min="1"
                max="100"
                value={notificationSettings.max_notifications_per_hour}
                onChange={(e) =>
                  updateSetting(
                    "max_notifications_per_hour",
                    Number.parseInt(e.target.value, 10) || 1,
                  )
                }
              />
            </label>

            <label className="space-y-2 text-sm">
              <span className="font-medium text-foreground">
                Max notifications / day
              </span>
              <Input
                type="number"
                min="1"
                max="500"
                value={notificationSettings.max_notifications_per_day}
                onChange={(e) =>
                  updateSetting(
                    "max_notifications_per_day",
                    Number.parseInt(e.target.value, 10) || 1,
                  )
                }
              />
            </label>

            <label className="space-y-2 text-sm">
              <span className="font-medium text-foreground">
                Escalation delay (hours)
              </span>
              <Input
                type="number"
                min="1"
                max="48"
                value={notificationSettings.escalation_delay_hours}
                onChange={(e) =>
                  updateSetting(
                    "escalation_delay_hours",
                    Number.parseInt(e.target.value, 10) || 1,
                  )
                }
              />
            </label>

            <div className="space-y-2 text-sm">
              <span className="font-medium text-foreground">Escalation</span>
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant={
                    notificationSettings.escalation_enabled
                      ? "default"
                      : "outline"
                  }
                  onClick={() => updateSetting("escalation_enabled", true)}
                >
                  Enabled
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={
                    !notificationSettings.escalation_enabled
                      ? "default"
                      : "outline"
                  }
                  onClick={() => updateSetting("escalation_enabled", false)}
                >
                  Disabled
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Notification settings unavailable.
          </p>
        )}

        <div className="flex justify-end">
          <Button
            type="button"
            onClick={() => void handleSaveNotifications()}
            disabled={!notificationSettings || notificationSaving}
          >
            {notificationSaving ? "Saving..." : "Save Notification Settings"}
          </Button>
        </div>
      </div>
    </section>
  );
}
