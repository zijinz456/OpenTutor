"use client";

import { useState } from "react";
import type { NextActionResponse } from "@/lib/api";
import { Button } from "@/components/ui/button";

interface AgentFocusStripProps {
  activeGoalTitle?: string | null;
  activeTaskTitle?: string | null;
  nextAction?: NextActionResponse | null;
  queueing: boolean;
  onOpenActivity: () => void;
  onQueueNextAction: () => void;
}

export function AgentFocusStrip({
  activeGoalTitle,
  activeTaskTitle,
  nextAction,
  queueing,
  onOpenActivity,
  onQueueNextAction,
}: AgentFocusStripProps) {
  const [expanded, setExpanded] = useState(false);

  if (!activeGoalTitle && !activeTaskTitle && !nextAction) {
    return null;
  }

  return (
    <div
      data-testid="agent-focus-strip"
      className="border-b border-border bg-muted/50 px-4 py-1.5 shrink-0"
    >
      {/* Collapsed: single line summary */}
      <div className="flex items-center gap-3 min-h-[28px]">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="text-[11px] text-muted-foreground hover:text-foreground transition-colors shrink-0"
        >
          {expanded ? "\u25BC" : "\u25B6"}
        </button>

        <div className="flex items-center gap-2 flex-1 min-w-0 overflow-hidden">
          {activeGoalTitle && (
            <span className="text-xs text-foreground font-medium truncate">
              Goal: {activeGoalTitle}
            </span>
          )}
          {activeTaskTitle && (
            <>
              <span className="text-muted-foreground text-[10px]">/</span>
              <span className="text-xs text-success truncate">
                Running: {activeTaskTitle}
              </span>
            </>
          )}
          {nextAction && !activeTaskTitle && (
            <>
              <span className="text-muted-foreground text-[10px]">/</span>
              <span className="text-xs text-muted-foreground truncate">
                Next: {nextAction.title}
              </span>
            </>
          )}
        </div>

        <div className="flex shrink-0 gap-2">
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={onOpenActivity}
          >
            Activity
          </Button>
          {nextAction && (
            <Button
              type="button"
              variant="outline"
              size="xs"
              data-testid="agent-focus-queue-next-action"
              onClick={onQueueNextAction}
              disabled={!nextAction.queue_ready || queueing}
            >
              {queueing ? "Queueing..." : (nextAction.queue_label || "Queue")}
            </Button>
          )}
        </div>
      </div>

      {/* Expanded: full details */}
      {expanded && (
        <div className="mt-2 pb-1 flex flex-col gap-1.5 pl-6">
          {nextAction && (
            <>
              <p className="text-sm font-medium text-foreground">{nextAction.title}</p>
              <p className="text-xs text-muted-foreground">{nextAction.recommended_action}</p>
              <p className="text-[11px] text-muted-foreground/70">{nextAction.reason}</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
