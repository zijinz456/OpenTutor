"use client";

import { useEffect, useRef, type RefObject } from "react";

type Orientation = "horizontal" | "vertical" | "both";

/**
 * Implements the roving tabindex pattern for composite widgets (lists, grids, toolbars).
 * Only the currently active item has tabIndex={0}; all others have tabIndex={-1}.
 * Arrow keys move focus between items within the container.
 */
export function useRovingTabindex(
  containerRef: RefObject<HTMLElement | null>,
  orientation: Orientation = "vertical",
) {
  const currentIndexRef = useRef(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const getItems = (): HTMLElement[] =>
      Array.from(
        container.querySelectorAll<HTMLElement>(
          '[role="menuitem"], [role="tab"], [role="option"], [role="radio"], [role="listitem"][tabindex]',
        ),
      );

    const updateTabIndices = (items: HTMLElement[], activeIdx: number) => {
      items.forEach((item, i) => {
        item.setAttribute("tabindex", i === activeIdx ? "0" : "-1");
      });
    };

    // Initialize: set tabindex on all items
    const items = getItems();
    if (items.length > 0) {
      updateTabIndices(items, currentIndexRef.current);
    }

    const isForward = (key: string): boolean => {
      if (orientation === "horizontal") return key === "ArrowRight";
      if (orientation === "vertical") return key === "ArrowDown";
      return key === "ArrowRight" || key === "ArrowDown";
    };

    const isBackward = (key: string): boolean => {
      if (orientation === "horizontal") return key === "ArrowLeft";
      if (orientation === "vertical") return key === "ArrowUp";
      return key === "ArrowLeft" || key === "ArrowUp";
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      const freshItems = getItems();
      if (freshItems.length === 0) return;

      let idx = currentIndexRef.current;

      if (isForward(e.key)) {
        e.preventDefault();
        idx = (idx + 1) % freshItems.length;
      } else if (isBackward(e.key)) {
        e.preventDefault();
        idx = (idx - 1 + freshItems.length) % freshItems.length;
      } else if (e.key === "Home") {
        e.preventDefault();
        idx = 0;
      } else if (e.key === "End") {
        e.preventDefault();
        idx = freshItems.length - 1;
      } else {
        return;
      }

      currentIndexRef.current = idx;
      updateTabIndices(freshItems, idx);
      freshItems[idx].focus();
    };

    container.addEventListener("keydown", handleKeyDown);

    return () => {
      container.removeEventListener("keydown", handleKeyDown);
    };
  }, [containerRef, orientation]);
}
