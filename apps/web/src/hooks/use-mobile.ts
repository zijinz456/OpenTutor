import { useSyncExternalStore } from "react";

/**
 * Reactive hook that returns true when the viewport width is below
 * the given breakpoint (default 768 px — Tailwind `md`).
 */
export function useIsMobile(breakpoint = 768) {
  const subscribe = (onStoreChange: () => void) => {
    if (typeof window === "undefined") {
      return () => {};
    }

    const mql = window.matchMedia(`(max-width: ${breakpoint - 1}px)`);
    const handler = () => onStoreChange();
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  };

  const getSnapshot = () => {
    if (typeof window === "undefined") {
      return false;
    }
    return window.matchMedia(`(max-width: ${breakpoint - 1}px)`).matches;
  };

  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
