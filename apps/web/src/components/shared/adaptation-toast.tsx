/**
 * Adaptation toast — notifies the user when the Block Decision Engine
 * modifies the workspace layout, with an undo option and optional
 * intervention feedback (thumbs up/down).
 */

import { toast } from "sonner";
import { Brain, ThumbsUp, ThumbsDown } from "lucide-react";
import type { BlockUpdateOp } from "@/lib/api";
import { request } from "@/lib/api/client";

const ACTION_LABELS: Record<string, string> = {
  add: "Added",
  remove: "Removed",
  resize: "Resized",
  reorder: "Reordered",
  update_config: "Updated",
};

async function submitFeedback(interventionId: string, feedback: "helpful" | "not_helpful") {
  try {
    await request("/blocks/intervention-feedback", {
      method: "POST",
      body: JSON.stringify({ intervention_id: interventionId, feedback }),
    });
  } catch {
    // Best-effort — don't disrupt UX on failure
  }
}

export function showAdaptationToast(
  explanation: string,
  operations: BlockUpdateOp[],
  onUndo?: () => void,
  interventionIds?: Record<string, string>,
): void {
  const description = operations
    .map((op) => `${ACTION_LABELS[op.action] ?? op.action} ${op.block_type} — ${op.reason}`)
    .join("\n");

  // If there are tracked interventions, show feedback buttons
  const firstInterventionId = interventionIds ? Object.values(interventionIds)[0] : undefined;

  toast(explanation, {
    description: (
      <div className="space-y-2">
        <p className="text-xs text-muted-foreground whitespace-pre-line">{description}</p>
        {firstInterventionId && (
          <div className="flex items-center gap-2 pt-1">
            <span className="text-xs text-muted-foreground">Was this helpful?</span>
            <button
              type="button"
              title="Helpful"
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs hover:bg-green-100 dark:hover:bg-green-900/30 transition-colors"
              onClick={() => {
                submitFeedback(firstInterventionId, "helpful");
                toast.dismiss();
              }}
            >
              <ThumbsUp className="h-3 w-3" />
            </button>
            <button
              type="button"
              title="Not helpful"
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors"
              onClick={() => {
                submitFeedback(firstInterventionId, "not_helpful");
                toast.dismiss();
              }}
            >
              <ThumbsDown className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>
    ),
    action: onUndo ? { label: "Undo", onClick: onUndo } : undefined,
    duration: 10000,
    icon: <Brain className="h-4 w-4 text-purple-500" />,
  });
}
