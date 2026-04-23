/**
 * Zustand store for "Panic Mode" — one-click dim-everything for ADHD overwhelm
 * (Phase 14 T2, plan `plan/adhd_ux_full_phase14.md`).
 *
 * Design notes
 * ------------
 * * **Persisted in localStorage.** Unlike the daily-session store we
 *   *do* want panic state to survive a refresh: if the user flipped it
 *   on because the dashboard was too much, reloading the page should
 *   not drop them back into the firehose. The key is a single boolean
 *   string — no migration surface.
 * * **`enabledAt` timestamp** is recorded whenever panic flips on so
 *   `<PanicOverlay>` can show its "Exit Panic Mode?" CTA after 60s on
 *   the dashboard (plan §2c dashboard guard). Plain `Date.now()` — we
 *   don't need monotonic time; the guard is a safety net, not a deadline.
 * * **SSR safety.** Next.js runs the store factory on the server, so
 *   every `window`/`localStorage` touch is guarded by a `typeof window`
 *   check. `readInitial()` returns `false` on the server and the hydration
 *   mismatch is negligible — the overlay effect only runs client-side.
 */

import { create } from "zustand";

interface PanicState {
  enabled: boolean;
  /** Timestamp (ms) when panic was last turned on. Null while disabled.
   *  Used by the dashboard guard in `<PanicOverlay>`. */
  enabledAt: number | null;
  toggle: () => void;
  enable: () => void;
  disable: () => void;
}

const STORAGE_KEY = "panic_mode_on";

/** Read the persisted flag on store construction. Returns `false` under
 *  SSR because `window` is undefined on the server. */
function readInitial(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(STORAGE_KEY) === "true";
}

export const usePanicStore = create<PanicState>((set, get) => ({
  enabled: readInitial(),
  enabledAt: readInitial() ? Date.now() : null,
  toggle: () => {
    const next = !get().enabled;
    set({ enabled: next, enabledAt: next ? Date.now() : null });
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, next ? "true" : "false");
    }
  },
  enable: () => {
    set({ enabled: true, enabledAt: Date.now() });
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, "true");
    }
  },
  disable: () => {
    set({ enabled: false, enabledAt: null });
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, "false");
    }
  },
}));
