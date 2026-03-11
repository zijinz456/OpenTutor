"use client";

import { useChatStore } from "@/store/chat";
import type { ClarifyOption } from "@/lib/api";
import { cn } from "@/lib/utils";
import { HelpCircle } from "lucide-react";

interface ClarifyCardProps {
  clarify: ClarifyOption;
  courseId: string;
}

/**
 * Interactive option buttons rendered when an agent requests clarification
 * before executing a task (OpenClaw Inputs pattern).
 *
 * Each button sends a JSON clarify message back to the orchestrator.
 */
export function ClarifyCard({ clarify, courseId }: ClarifyCardProps) {
  const sendClarifyResponse = useChatStore((s) => s.sendClarifyResponse);
  const isStreaming = useChatStore((s) => s.isStreaming);

  if (!clarify.options || clarify.options.length === 0) return null;

  return (
    <div role="group" aria-label="Clarification options" className="mt-2 flex flex-wrap gap-1.5">
      {clarify.options.map((option, index) => (
        <button
          key={`${clarify.key}-${index}`}
          type="button"
          disabled={isStreaming}
          aria-label={`Choose: ${option}`}
          onClick={() => sendClarifyResponse(courseId, clarify.key, option)}
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium",
            "bg-muted/30 text-foreground/80",
            "transition-all hover:bg-muted/50 card-shadow",
            "cursor-pointer select-none border border-border/60",
            "disabled:opacity-50 disabled:cursor-not-allowed",
          )}
        >
          <HelpCircle className="size-3" aria-hidden="true" />
          <span>{option}</span>
        </button>
      ))}
    </div>
  );
}
