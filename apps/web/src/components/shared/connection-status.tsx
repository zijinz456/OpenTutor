"use client";

import { useState, useEffect } from "react";
import { WifiOff } from "lucide-react";

export function ConnectionStatus() {
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const handleOnline = () => setOffline(false);
    const handleOffline = () => setOffline(true);

    // Check initial state
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      setOffline(true);
    }

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  if (!offline) return null;

  return (
    <div className="fixed top-0 left-0 right-0 z-[60] bg-destructive/90 text-destructive-foreground text-center py-1.5 text-xs font-medium flex items-center justify-center gap-2">
      <WifiOff className="size-3.5" />
      You are offline. Changes will sync when reconnected.
    </div>
  );
}
