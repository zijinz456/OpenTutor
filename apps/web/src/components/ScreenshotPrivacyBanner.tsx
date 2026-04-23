"use client";

/**
 * Screenshot privacy warning banner (Phase 4 T6).
 *
 * Short amber banner reminding the learner that vision models ingest
 * EVERYTHING visible in an image — including credentials, API keys,
 * email addresses, and any other private data. Safe default: render
 * above the screenshot drop zone (T7 will wire it in), but the
 * component is deliberately standalone / stateless so any caller can
 * place it wherever privacy context is relevant.
 *
 * Optional ``dismissible`` mode shows a close button; clicking it
 * fires ``onDismiss`` and unmounts the banner (returns ``null``).
 */

import { useState } from "react";
import { X } from "lucide-react";

interface Props {
  /**
   * When true, renders a close button. Clicking it calls ``onDismiss``
   * (if provided) and hides the banner. Default false — the banner is
   * persistent so the privacy reminder stays visible.
   */
  dismissible?: boolean;
  /** Fired once when the user clicks the close button. */
  onDismiss?: () => void;
}

const WARNING_TEXT =
  "\u26A0\uFE0F Don't capture credentials, API keys, emails, or private data. " +
  "Vision models read everything in the image.";

export function ScreenshotPrivacyBanner({ dismissible = false, onDismiss }: Props) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  const handleDismiss = () => {
    setDismissed(true);
    onDismiss?.();
  };

  return (
    <div
      data-testid="screenshot-privacy-banner"
      role="alert"
      className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200"
    >
      <span className="flex-1 leading-snug">{WARNING_TEXT}</span>
      {dismissible && (
        <button
          type="button"
          onClick={handleDismiss}
          aria-label="Dismiss privacy warning"
          data-testid="screenshot-privacy-banner-dismiss"
          className="shrink-0 rounded p-0.5 text-amber-700 hover:bg-amber-100 hover:text-amber-900 dark:text-amber-300 dark:hover:bg-amber-900/50 dark:hover:text-amber-100"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
