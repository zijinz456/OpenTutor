"use client";

import { ChatView } from "./chat-view";
import { cn } from "@/lib/utils";

interface ChatDrawerProps {
  courseId: string;
  open: boolean;
  aiActionsEnabled?: boolean;
}

export function ChatDrawer({ courseId, open, aiActionsEnabled = true }: ChatDrawerProps) {
  return (
    <div
      className={cn(
        "fixed top-0 right-0 z-40 h-full w-full sm:w-[420px] md:w-[480px]",
        "bg-background border-l border-border shadow-2xl",
        "transition-transform duration-300 ease-in-out",
        open ? "translate-x-0" : "translate-x-full",
      )}
    >
      {open && (
        <ChatView courseId={courseId} aiActionsEnabled={aiActionsEnabled} />
      )}
    </div>
  );
}
