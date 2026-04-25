"use client";

/**
 * `<GenerateRoomCTA>` — Phase 16b Bundle B (+ v2 track-header variant).
 *
 * Small "Generate room" button that opens `<GenerateRoomModal>`. Self-
 * contained: drop it next to a track/path block on the dashboard or any
 * track page and it manages its own modal state.
 *
 * Why a separate component (instead of the modal exposing a built-in
 * trigger): callers want to render the pill in different layouts —
 * inside a chips row, beside a track card, in a kebab menu — without
 * duplicating modal-state plumbing each time.
 *
 * Variants
 * --------
 *   - `dashboard-rail` (default): low-key pill that fits inside a
 *     side-rail or a row of chips. Used on the dashboard.
 *   - `track-header`: more prominent button placed in the header /
 *     summary area of `/tracks/[slug]`. Same copy + same modal —
 *     just a beefier button so it actually reads as the primary CTA
 *     on the track-detail screen.
 *
 * Both variants open the same modal with the same props; only the
 * trigger styling differs. We expose a `data-testid` per variant
 * (`generate-room-cta-${variant}`) so the page-level tests can target
 * the right instance even when both happen to mount on screen.
 */

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { GenerateRoomModal } from "./generate-room-modal";

type Variant = "dashboard-rail" | "track-header";

interface GenerateRoomCTAProps {
  pathId: string;
  courseId: string;
  pathSlug: string;
  /** Visual treatment. Defaults to `dashboard-rail` so existing call
   *  sites keep their previous look without code churn. */
  variant?: Variant;
}

/** Tailwind class set per variant. Kept inline (not a lookup map) so
 *  Tailwind's content scanner picks the classes up at build time. */
function buttonClassFor(variant: Variant): string {
  if (variant === "track-header") {
    // Track-header: filled brand-coloured button with default size so
    // it reads as the primary action in the track header strip.
    // Uses existing `--brand` tokens — no new colours introduced.
    return "inline-flex items-center gap-2 rounded-full bg-brand px-5 py-2 text-sm font-medium text-brand-foreground transition-all hover:opacity-90 hover:shadow-md";
  }
  // dashboard-rail (existing pill).
  return "inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/30 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted/50";
}

export function GenerateRoomCTA({
  pathId,
  courseId,
  pathSlug,
  variant = "dashboard-rail",
}: GenerateRoomCTAProps) {
  const [isOpen, setIsOpen] = useState(false);

  const iconSize = variant === "track-header" ? "size-4" : "size-3.5";

  return (
    <>
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        data-testid={`generate-room-cta-${variant}`}
        className={buttonClassFor(variant)}
        style={{ transitionDuration: "var(--dur-fast)" }}
      >
        <Sparkles className={iconSize} />
        Generate room
      </button>

      {isOpen ? (
        <GenerateRoomModal
          pathId={pathId}
          courseId={courseId}
          pathSlug={pathSlug}
          isOpen={isOpen}
          onClose={() => setIsOpen(false)}
        />
      ) : null}
    </>
  );
}
