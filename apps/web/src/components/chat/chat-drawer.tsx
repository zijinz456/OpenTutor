"use client";

import { useCallback, useRef, useState } from "react";
import { ChatView } from "./chat-view";
import { cn } from "@/lib/utils";
import { BottomSheet } from "@/components/ui/bottom-sheet";

interface ChatDrawerProps {
  courseId: string;
  open: boolean;
  onOpenChange?: (open: boolean) => void;
  aiActionsEnabled?: boolean;
}

/**
 * On mobile (< 768px), renders as a bottom sheet with swipe-down to dismiss.
 * On desktop, renders as the original side drawer.
 */
export function ChatDrawer({ courseId, open, onOpenChange, aiActionsEnabled = true }: ChatDrawerProps) {
  // Swipe-down gesture state for the mobile drawer fallback
  const drawerRef = useRef<HTMLDivElement>(null);
  const dragState = useRef<{ startY: number; currentY: number } | null>(null);
  const [dragOffset, setDragOffset] = useState(0);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    // Only initiate drag from top 48px of the drawer
    const rect = drawerRef.current?.getBoundingClientRect();
    if (!rect || e.clientY - rect.top > 48) return;
    dragState.current = { startY: e.clientY, currentY: e.clientY };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragState.current) return;
    dragState.current.currentY = e.clientY;
    const dy = Math.max(0, e.clientY - dragState.current.startY);
    setDragOffset(dy);
  }, []);

  const handlePointerUp = useCallback(() => {
    if (!dragState.current) return;
    const dy = dragState.current.currentY - dragState.current.startY;
    dragState.current = null;
    setDragOffset(0);
    if (dy > 120) {
      onOpenChange?.(false);
    }
  }, [onOpenChange]);

  return (
    <>
      {/* Mobile: bottom sheet (< md) */}
      <div className="md:hidden">
        <BottomSheet open={open} onOpenChange={(v) => onOpenChange?.(v)} title="Chat">
          <div className="h-[75dvh]">
            {open && <ChatView courseId={courseId} aiActionsEnabled={aiActionsEnabled} />}
          </div>
        </BottomSheet>
      </div>

      {/* Desktop: side drawer (>= md) */}
      <div
        ref={drawerRef}
        className={cn(
          "hidden md:block fixed top-0 right-0 z-40 h-full w-full sm:w-[420px] md:w-[480px]",
          "bg-card border-l border-border/40 shadow-2xl",
          "transition-transform duration-300 ease-in-out",
          open ? "translate-x-0" : "translate-x-full",
        )}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        style={dragOffset ? { transform: `translateY(${dragOffset}px)`, transition: "none" } : undefined}
      >
        {open && (
          <ChatView courseId={courseId} aiActionsEnabled={aiActionsEnabled} />
        )}
      </div>
    </>
  );
}
