/**
 * Adaptation toast — notifies the user when the Block Decision Engine
 * modifies the workspace layout, with an undo option.
 */

import { toast } from "sonner";
import { Brain } from "lucide-react";
import type { BlockUpdateOp } from "@/lib/api";

const ACTION_LABELS: Record<string, string> = {
  add: "Added",
  remove: "Removed",
  resize: "Resized",
  reorder: "Reordered",
  update_config: "Updated",
};

export function showAdaptationToast(
  explanation: string,
  operations: BlockUpdateOp[],
  onUndo?: () => void,
): void {
  const description = operations
    .map((op) => `${ACTION_LABELS[op.action] ?? op.action} ${op.block_type} — ${op.reason}`)
    .join("\n");

  toast(explanation, {
    description,
    action: onUndo ? { label: "Undo", onClick: onUndo } : undefined,
    duration: 8000,
    icon: <Brain className="h-4 w-4 text-purple-500" />,
  });
}
