"use client";

import { cn } from "@/lib/utils";
import { Wrench, Check } from "lucide-react";

interface ToolStatusProps {
  status: {
    tool: string;
    status: "running" | "complete";
    explanation?: string;
  } | null;
}

/**
 * Small status bar that appears when a tool is running or just completed.
 * Animates in/out via CSS transitions.
 */
export function ToolStatus({ status }: ToolStatusProps) {
  if (!status) return null;

  const isRunning = status.status === "running";
  const label =
    status.explanation || status.tool.replace(/_/g, " ");

  return (
    <div
      className={cn(
        "flex shrink-0 items-center gap-2 border-t px-3 py-1.5 text-xs",
        "animate-in fade-in slide-in-from-bottom-1 duration-200",
        isRunning
          ? "bg-muted/50 text-muted-foreground"
          : "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400",
      )}
    >
      {isRunning ? (
        <>
          <Wrench className="size-3 animate-spin" />
          <span>Running: {label}...</span>
        </>
      ) : (
        <>
          <Check className="size-3" />
          <span>Complete: {label}</span>
        </>
      )}
    </div>
  );
}
