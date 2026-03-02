import { useSyncExternalStore } from "react";

/**
 * Reactive hook that tracks browser online/offline status.
 * Uses `useSyncExternalStore` for SSR safety — returns `true`
 * on the server to avoid hydration mismatches.
 */
export function useOnlineStatus(): { isOnline: boolean } {
  const subscribe = (onStoreChange: () => void) => {
    window.addEventListener("online", onStoreChange);
    window.addEventListener("offline", onStoreChange);
    return () => {
      window.removeEventListener("online", onStoreChange);
      window.removeEventListener("offline", onStoreChange);
    };
  };

  const getSnapshot = () => navigator.onLine;

  // Server snapshot: assume online to avoid flash of offline banner on hydration
  const getServerSnapshot = () => true;

  const isOnline = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  return { isOnline };
}
