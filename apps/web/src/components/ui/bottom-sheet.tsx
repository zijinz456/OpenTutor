"use client";

import * as React from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { cn } from "@/lib/utils";

interface BottomSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  children: React.ReactNode;
}

/**
 * Bottom sheet that slides up from bottom on mobile, acts as centered dialog on desktop.
 * Uses Radix Dialog for accessibility (focus trap, escape to close).
 * Supports swipe-down to dismiss via pointer events.
 */
export function BottomSheet({ open, onOpenChange, title, children }: BottomSheetProps) {
  const contentRef = React.useRef<HTMLDivElement>(null);
  const dragState = React.useRef<{ startY: number; currentY: number } | null>(null);

  const handlePointerDown = React.useCallback((e: React.PointerEvent) => {
    // Only handle touches on the drag handle area (first 40px)
    const rect = contentRef.current?.getBoundingClientRect();
    if (!rect) return;
    if (e.clientY - rect.top > 40) return;
    dragState.current = { startY: e.clientY, currentY: e.clientY };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const handlePointerMove = React.useCallback((e: React.PointerEvent) => {
    if (!dragState.current || !contentRef.current) return;
    dragState.current.currentY = e.clientY;
    const dy = Math.max(0, e.clientY - dragState.current.startY);
    contentRef.current.style.transform = `translateY(${dy}px)`;
  }, []);

  const handlePointerUp = React.useCallback(() => {
    if (!dragState.current || !contentRef.current) return;
    const dy = dragState.current.currentY - dragState.current.startY;
    contentRef.current.style.transform = "";
    if (dy > 100) {
      onOpenChange(false);
    }
    dragState.current = null;
  }, [onOpenChange]);

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className={cn(
            "fixed inset-0 z-50 bg-black/50",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
            "data-[state=open]:animate-in data-[state=open]:fade-in-0",
          )}
        />
        <DialogPrimitive.Content
          ref={contentRef}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          className={cn(
            // Mobile: bottom sheet
            "fixed z-50 w-full outline-none",
            "bottom-0 left-0 right-0 max-h-[85dvh]",
            "rounded-t-2xl border-t bg-background shadow-elevated",
            "data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom",
            "data-[state=closed]:animate-out data-[state=closed]:slide-out-to-bottom",
            "duration-300",
            // Desktop: centered dialog
            "md:bottom-auto md:left-[50%] md:top-[50%] md:translate-x-[-50%] md:translate-y-[-50%]",
            "md:max-w-lg md:max-h-[80vh] md:rounded-xl md:border",
            "md:data-[state=open]:slide-in-from-bottom-0 md:data-[state=open]:zoom-in-95",
            "md:data-[state=closed]:zoom-out-95",
          )}
        >
          {/* Drag handle — visible on mobile */}
          <div className="flex justify-center pt-3 pb-1 md:hidden touch-none">
            <div className="h-1.5 w-10 rounded-full bg-muted-foreground/30" />
          </div>

          {title && (
            <DialogPrimitive.Title className="px-4 pb-2 pt-1 text-sm font-semibold md:pt-4">
              {title}
            </DialogPrimitive.Title>
          )}

          <div className="overflow-y-auto px-4 pb-4 md:pt-2">
            {children}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
