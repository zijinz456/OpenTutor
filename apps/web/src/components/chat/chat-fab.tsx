"use client";

import { MessageCircle, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatFabProps {
  open: boolean;
  onToggle: () => void;
  hasUnread?: boolean;
}

export function ChatFab({ open, onToggle, hasUnread }: ChatFabProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={open ? "Close chat" : "Open chat"}
      className={cn(
        "fixed bottom-6 right-6 z-50 flex items-center justify-center",
        "w-14 h-14 rounded-full shadow-lg transition-all duration-200",
        "hover:scale-105 active:scale-95",
        open
          ? "bg-muted text-muted-foreground hover:bg-muted/80"
          : "bg-primary text-primary-foreground hover:bg-primary/90",
      )}
    >
      {open ? <X className="size-5" /> : <MessageCircle className="size-5" />}
      {!open && hasUnread && (
        <span className="absolute top-1 right-1 w-3 h-3 bg-destructive rounded-full border-2 border-background" />
      )}
    </button>
  );
}
