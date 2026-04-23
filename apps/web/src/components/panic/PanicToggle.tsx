"use client";

/**
 * `<PanicToggle>` — header pill that flips Panic Mode on/off.
 *
 * Phase 14 T2 (plan §2b). Factual label, *not* guilt-y:
 *   off → "Panic"  (offers the escape hatch)
 *   on  → "Calm"   (confirms you're in it)
 *
 * The emoji prefix is a visual cue, not the primary label — screen readers
 * pick up the full text. Click flips the store; `<PanicOverlay>` handles
 * the actual UI dimming and Esc-to-exit.
 */

import { usePanicStore } from "@/store/panic";
import { cn } from "@/lib/utils";

interface Props {
  className?: string;
}

export function PanicToggle({ className }: Props) {
  const enabled = usePanicStore((s) => s.enabled);
  const toggle = usePanicStore((s) => s.toggle);

  return (
    <button
      type="button"
      onClick={toggle}
      data-testid="panic-toggle"
      title="Hide all non-essential UI. Esc to exit."
      aria-pressed={enabled}
      aria-label={enabled ? "Exit panic mode" : "Enter panic mode"}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium",
        "border border-border bg-muted/60 hover:bg-muted transition-colors",
        enabled && "bg-success-muted text-success-foreground",
        className,
      )}
    >
      <span aria-hidden="true">{enabled ? "🟢" : "🧘"}</span>
      <span>{enabled ? "Calm" : "Panic"}</span>
    </button>
  );
}
