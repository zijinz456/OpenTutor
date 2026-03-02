"use client";

import { useState } from "react";
import { WifiOff, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useOnlineStatus } from "@/hooks/use-online-status";

/**
 * A small, dismissible banner displayed at the top of the page when
 * the browser loses its network connection. Reappears automatically
 * on subsequent offline transitions.
 */
export function OfflineBanner() {
  const { isOnline } = useOnlineStatus();
  const [dismissed, setDismissed] = useState(false);

  // Reset dismiss state when the connection comes back so the banner
  // will appear again if the user goes offline a second time.
  if (isOnline && dismissed) {
    setDismissed(false);
  }

  if (isOnline || dismissed) return null;

  return (
    <div
      role="alert"
      className={cn(
        "flex items-center gap-2 px-3 py-2 border-b text-xs",
        "bg-amber-50 border-amber-200 text-amber-900",
        "dark:bg-amber-950/40 dark:border-amber-800 dark:text-amber-200",
      )}
    >
      <WifiOff className="h-3.5 w-3.5 shrink-0" />
      <span className="flex-1">
        You are offline. Some features may be unavailable.
      </span>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="text-amber-700 hover:text-amber-900 dark:text-amber-400 dark:hover:text-amber-200"
        title="Dismiss"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
