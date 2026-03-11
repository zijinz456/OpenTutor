"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { NotesSection } from "@/components/sections/notes-section";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { useFocusTrap } from "@/hooks/use-focus-trap";
import { cn } from "@/lib/utils";

interface NotesDrawerProps {
  courseId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  aiActionsEnabled?: boolean;
}

/** True when viewport is below the md breakpoint (768px). */
function useIsMobile() {
  const [mobile, setMobile] = useState(() => (
    typeof window !== "undefined" ? window.matchMedia("(max-width: 767px)").matches : false
  ));
  useEffect(() => {
    const mql = window.matchMedia("(max-width: 767px)");
    const handler = (e: MediaQueryListEvent) => setMobile(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);
  return mobile;
}

/**
 * Right-side sliding panel for notes, mirroring the ChatDrawer pattern.
 * Mobile (< md): bottom sheet. Desktop (>= md): side drawer.
 */
export function NotesDrawer({ courseId, open, onOpenChange, aiActionsEnabled = true }: NotesDrawerProps) {
  const drawerRef = useRef<HTMLDivElement>(null);
  const isMobile = useIsMobile();

  useFocusTrap(drawerRef, open);

  // Close on Escape key
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onOpenChange]);

  return (
    <>
      {/* Mobile: bottom sheet — only mount when actually mobile to avoid Radix portal leak */}
      {isMobile && (
        <BottomSheet open={open} onOpenChange={onOpenChange} title="Notes">
          <div className="h-[75dvh]">
            {open && <NotesSection courseId={courseId} aiActionsEnabled={aiActionsEnabled} />}
          </div>
        </BottomSheet>
      )}

      {/* Desktop: side drawer (>= md) */}
      <div
        ref={drawerRef}
        role="complementary"
        aria-label="Notes panel"
        aria-hidden={!open ? "true" : undefined}
        className={cn(
          "hidden md:flex md:flex-col fixed top-0 right-0 z-40 h-full w-full sm:w-[420px] md:w-[480px]",
          "bg-card border-l border-border/40 shadow-2xl",
          "transition-transform duration-300 ease-in-out",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        {/* Drawer header with close button */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border/40 shrink-0">
          <span className="text-sm font-semibold text-foreground">Notes</span>
          <button
            onClick={() => onOpenChange(false)}
            className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-md hover:bg-muted/50"
            aria-label="Close notes panel"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Notes content */}
        {open && (
          <div className="flex-1 min-h-0 overflow-hidden">
            <NotesSection courseId={courseId} aiActionsEnabled={aiActionsEnabled} />
          </div>
        )}
      </div>
    </>
  );
}
