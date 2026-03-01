/**
 * Notifications store using Zustand.
 * Manages push notification subscription state and interactions with the backend.
 */

import { create } from "zustand";
import { getVapidKey, subscribePush, unsubscribePush } from "@/lib/api";

/**
 * Convert a URL-safe base64 VAPID key to a Uint8Array for the PushManager API.
 */
function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

interface NotificationState {
  pushSupported: boolean;
  pushPermission: NotificationPermission | null;
  isSubscribed: boolean;
  subscribing: boolean;
  error: string | null;

  checkSubscription: () => Promise<void>;
  subscribe: () => Promise<void>;
  unsubscribe: () => Promise<void>;
}

export const useNotificationStore = create<NotificationState>((set) => ({
  pushSupported: false,
  pushPermission: null,
  isSubscribed: false,
  subscribing: false,
  error: null,

  checkSubscription: async () => {
    const supported =
      typeof window !== "undefined" &&
      "serviceWorker" in navigator &&
      "PushManager" in window &&
      "Notification" in window;

    if (!supported) {
      set({ pushSupported: false, pushPermission: null, isSubscribed: false });
      return;
    }

    const permission = Notification.permission;
    let isSubscribed = false;

    try {
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();
      isSubscribed = subscription !== null;
    } catch {
      // Service worker not ready yet or push not available
    }

    set({ pushSupported: true, pushPermission: permission, isSubscribed });
  },

  subscribe: async () => {
    set({ subscribing: true, error: null });
    try {
      const permission = await Notification.requestPermission();
      set({ pushPermission: permission });

      if (permission !== "granted") {
        set({ subscribing: false });
        return;
      }

      // Fetch VAPID public key from backend
      const { public_key } = await getVapidKey();
      const applicationServerKey = urlBase64ToUint8Array(public_key);

      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: applicationServerKey.buffer as ArrayBuffer,
      });

      // Extract keys from the subscription
      const rawKey = subscription.getKey("p256dh");
      const rawAuth = subscription.getKey("auth");

      if (!rawKey || !rawAuth) {
        throw new Error("Failed to get push subscription keys");
      }

      // Register subscription with backend
      await subscribePush({
        endpoint: subscription.endpoint,
        p256dh_key: arrayBufferToBase64(rawKey),
        auth_key: arrayBufferToBase64(rawAuth),
        user_agent: navigator.userAgent,
      });

      set({ isSubscribed: true, subscribing: false });
    } catch (e) {
      set({ error: (e as Error).message, subscribing: false });
    }
  },

  unsubscribe: async () => {
    set({ subscribing: true, error: null });
    try {
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();

      if (subscription) {
        // Unregister from backend
        await unsubscribePush({ endpoint: subscription.endpoint });
        // Unsubscribe locally
        await subscription.unsubscribe();
      }

      set({ isSubscribed: false, subscribing: false });
    } catch (e) {
      set({ error: (e as Error).message, subscribing: false });
    }
  },
}));
