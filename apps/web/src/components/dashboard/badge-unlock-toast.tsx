"use client";

/**
 * `<BadgeUnlockToast>` — calm one-shot unlock notification
 * (Phase 16c Bundle C — Subagent B).
 *
 * Renders a single floating panel in the top-right corner announcing one
 * badge unlock. The component is fully controlled: parent passes the
 * `badge` to show (or `null` to hide) and supplies an `onDismiss`
 * callback. It auto-hides after `autoDismissMs` (default 5s).
 *
 * ADHD §11 + spec C.4 "calm collectible":
 *   - NO sound, NO confetti, NO emoji explosion, NO shake.
 *   - Quiet slide-in via `--dur-normal` (200 ms).
 *   - One toast at a time — caller is responsible for sequencing.
 */

import { useEffect } from "react";
import { clsx } from "clsx";
import type { BadgeOut } from "@/lib/api/gamification";

export interface BadgeUnlockToastProps {
  /** The badge to announce; `null` renders nothing. */
  badge: BadgeOut | null;
  /** Called when the toast auto-hides or the user dismisses it. */
  onDismiss: () => void;
  /** Auto-dismiss timeout in ms; defaults to 5000. */
  autoDismissMs?: number;
}

export function BadgeUnlockToast({
  badge,
  onDismiss,
  autoDismissMs = 5000,
}: BadgeUnlockToastProps) {
  useEffect(() => {
    if (!badge) return;
    const id = setTimeout(() => {
      onDismiss();
    }, autoDismissMs);
    return () => {
      clearTimeout(id);
    };
  }, [badge, autoDismissMs, onDismiss]);

  if (!badge) {
    return null;
  }

  return (
    <div
      data-testid="badge-unlock-toast"
      role="status"
      aria-live="polite"
      className={clsx(
        "fixed right-4 top-4 z-50 max-w-xs rounded-2xl border border-border",
        "bg-card p-4 card-shadow text-foreground transition-opacity",
      )}
      style={{ transitionDuration: "var(--dur-normal, 200ms)" }}
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="text-xl leading-none text-foreground"
        >
          ★
        </span>
        <div className="flex-1 min-w-0">
          <p
            data-testid="badge-unlock-toast-title"
            className="text-sm font-semibold"
          >
            Unlocked: {badge.title}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {badge.description}
          </p>
        </div>
        <button
          type="button"
          data-testid="badge-unlock-toast-dismiss"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 rounded-full px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          ×
        </button>
      </div>
    </div>
  );
}
