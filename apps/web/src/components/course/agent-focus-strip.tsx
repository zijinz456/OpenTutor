"use client";

import { ArrowRight, Goal, PlayCircle, Workflow } from "lucide-react";
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
  if (!activeGoalTitle && !activeTaskTitle && !nextAction) {
    return null;
  }

  return (
    <div
      data-testid="agent-focus-strip"
      className="border-b border-indigo-200 bg-[linear-gradient(90deg,rgba(224,231,255,0.95),rgba(238,242,255,0.85))] px-4 py-3"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-indigo-700/80">
            <span className="inline-flex items-center gap-1 rounded-full border border-indigo-200 bg-white/70 px-2 py-0.5">
              <Workflow className="h-3.5 w-3.5" />
              Agent Focus
            </span>
            <span className="text-indigo-500/80">Goal</span>
            <ArrowRight className="h-3 w-3 text-indigo-400" />
            <span className="text-indigo-500/80">Next Action</span>
            <ArrowRight className="h-3 w-3 text-indigo-400" />
            <span className="text-indigo-500/80">Execute</span>
            <ArrowRight className="h-3 w-3 text-indigo-400" />
            <span className="text-indigo-500/80">Review</span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {activeGoalTitle && (
              <span className="inline-flex items-center gap-1 rounded-full border border-indigo-200 bg-white/80 px-2.5 py-1 text-xs font-medium text-indigo-900">
                <Goal className="h-3.5 w-3.5" />
                {activeGoalTitle}
              </span>
            )}
            {activeTaskTitle && (
              <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-800">
                <PlayCircle className="h-3.5 w-3.5" />
                Running: {activeTaskTitle}
              </span>
            )}
          </div>
          {nextAction && (
            <>
              <p className="mt-3 text-sm font-semibold text-slate-900">{nextAction.title}</p>
              <p className="mt-1 text-sm text-slate-700">{nextAction.recommended_action}</p>
              <p className="mt-1 text-xs text-slate-500">{nextAction.reason}</p>
            </>
          )}
        </div>

        <div className="flex shrink-0 flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="agent-focus-open-activity"
            onClick={onOpenActivity}
          >
            Open Activity
          </Button>
          {nextAction && (
            <Button
              type="button"
              size="sm"
              data-testid="agent-focus-queue-next-action"
              onClick={onQueueNextAction}
              disabled={!nextAction.queue_ready || queueing}
            >
              <Workflow className="mr-1 h-4 w-4" />
              {queueing ? "Queueing..." : (nextAction.queue_label || "Queue task")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
