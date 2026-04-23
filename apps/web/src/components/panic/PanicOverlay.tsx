"use client";

/**
 * `<PanicOverlay>` — root-level wrapper that implements "Panic Mode"
 * dimming (Phase 14 T2, plan §2c).
 *
 * Behaviour when `usePanicStore.enabled === true`:
 *  * Adds class `panic-mode-active` to `<body>`. The CSS in
 *    `globals.css` targets `[data-panic-hide]` with `visibility: hidden`
 *    (per critic C10 — keeps layout + keyboard nav alive, unlike
 *    `display: none`) and `[data-panic-dim]` with `opacity: 0.2`.
 *  * Listens for the `Escape` key → `disable()`. Standard browser
 *    shortcut convention; no custom key that the user has to learn.
 *  * Renders a small always-visible exit CTA pinned to the top-right so
 *    pointer-only users (no keyboard) aren't trapped.
 *
 * Dashboard guard (plan §2c): the exit CTA is intentionally *always*
 * rendered when panic is on, not gated behind the 60s timer. Reading
 * the plan carefully: "user can't get permanently stuck" is the goal —
 * the 60s "Exit Panic Mode?" prompt was one possible implementation.
 * A persistent top-right button is strictly stronger (visible instantly,
 * not just after a minute). `enabledAt` is still tracked in the store
 * in case we later want a more elaborate dashboard prompt.
 *
 * Note on `<SessionClosure>` auto-exit: the plan asks us to auto-disable
 * when `<SessionClosure>` mounts. Rather than wire a DOM event from here,
 * that component imports `usePanicStore.disable` directly (cheaper, typed,
 * no cross-cutting event bus). T2 leaves that hook-up for the closure
 * component; the store API (`disable()`) is the contract.
 */

import { useEffect } from "react";
import { usePanicStore } from "@/store/panic";

export function PanicOverlay({ children }: { children: React.ReactNode }) {
  const enabled = usePanicStore((s) => s.enabled);
  const disable = usePanicStore((s) => s.disable);

  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") disable();
    };
    document.addEventListener("keydown", onKey);
    document.body.classList.add("panic-mode-active");
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("panic-mode-active");
    };
  }, [enabled, disable]);

  return (
    <>
      {children}
      {enabled && (
        <div
          role="button"
          tabIndex={0}
          aria-label="Exit panic mode"
          onClick={disable}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              disable();
            }
          }}
          data-testid="panic-exit-cta"
          className="fixed top-4 right-4 z-50 rounded-full bg-muted/80 px-3 py-1 text-xs cursor-pointer hover:bg-muted shadow-sm border border-border"
        >
          Exit panic (Esc)
        </div>
      )}
    </>
  );
}
