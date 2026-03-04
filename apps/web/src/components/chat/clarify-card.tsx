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
 * Each button sends a [CLARIFY:key:value] message back to the orchestrator.
 */
export function ClarifyCard({ clarify, courseId }: ClarifyCardProps) {
  const sendClarifyResponse = useChatStore((s) => s.sendClarifyResponse);
  const isStreaming = useChatStore((s) => s.isStreaming);

  if (!clarify.options || clarify.options.length === 0) return null;

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {clarify.options.map((option, index) => (
        <button
          key={`${clarify.key}-${index}`}
          type="button"
          disabled={isStreaming}
          onClick={() => sendClarifyResponse(courseId, clarify.key, option)}
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium",
            "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
            "transition-all hover:bg-blue-100 dark:hover:bg-blue-900/50",
            "cursor-pointer select-none border border-blue-200 dark:border-blue-800",
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
