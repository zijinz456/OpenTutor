"use client";

import { useState, useEffect } from "react";
import { WifiOff } from "lucide-react";

export function ConnectionStatus() {
  // Always start false to prevent SSR mismatch and false positives
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const verify = async () => {
      // If browser says online, trust it
      if (navigator.onLine) {
        if (!cancelled) setOffline(false);
        return;
      }
      // Browser says offline — double-check with a real fetch
      try {
        const r = await fetch("/api/health", { method: "HEAD", cache: "no-store" });
        if (!cancelled) setOffline(!r.ok);
      } catch {
        if (!cancelled) setOffline(true);
      }
    };

    verify();
    const onOnline = () => { if (!cancelled) setOffline(false); };
    const onOffline = () => { verify(); };
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      cancelled = true;
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  if (!offline) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed top-0 left-0 right-0 z-[60] bg-destructive/90 text-destructive-foreground text-center py-2 text-xs font-medium flex items-center justify-center gap-2 animate-slide-up"
    >
      <WifiOff className="size-3.5" />
      You are offline. Changes will sync when reconnected.
    </div>
  );
}
