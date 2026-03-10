/**
 * Chat streaming event handlers — extracted from chat store.
 */

import type { ChatAction, ChatMessageMetadata, ClarifyOption, PlanProgressEvent, BlockUpdateOp, CognitiveState } from "@/lib/api";
import type { BlockType, BlockSize } from "@/lib/block-system/types";

export interface StreamEventHandlers {
  onContent: (content: string) => void;
  onAction: (action: ChatAction) => void;
  onPlanStep: (task: PlanProgressEvent) => void;
  onToolStatus: (tool: string, status: string, explanation?: string) => void;
  onToolProgress: (tool: string, message: string, step: number, total: number) => void;
  onClarify: (options: ClarifyOption[]) => void;
  onReplace: (content: string) => void;
  onDone: (sessionId: string, metadata?: ChatMessageMetadata | null, actions?: ChatAction[]) => void;
}

/**
 * Apply block decisions from the Block Decision Engine.
 * Translates BlockUpdateOps into workspace store batch operations.
 */
export async function applyBlockDecisions(
  result: { operations: BlockUpdateOp[]; cognitiveState: CognitiveState; explanation: string },
): Promise<void> {
  try {
    const { useWorkspaceStore } = await import("@/store/workspace");
    const ws = useWorkspaceStore.getState();

    // Always persist cognitive state for the badge
    if (result.cognitiveState) {
      ws.setCognitiveState(result.cognitiveState);
    }

    if (!result.operations.length) return;

    const batchOps: Array<
      | { action: "add"; type: BlockType; config?: Record<string, unknown>; size?: BlockSize }
      | { action: "remove"; blockId: string }
      | { action: "resize"; blockId: string; size: BlockSize }
      | { action: "update_config"; blockId: string; config: Record<string, unknown> }
    > = [];

    for (const op of result.operations) {
      if (op.action === "add") {
        batchOps.push({
          action: "add",
          type: op.block_type as BlockType,
          config: op.config,
          size: op.size as BlockSize | undefined,
        });
      } else if (op.action === "remove") {
        const block = ws.spaceLayout.blocks.find((b) => b.type === op.block_type);
        if (block) {
          batchOps.push({ action: "remove", blockId: block.id });
        }
      } else if (op.action === "resize") {
        const block = ws.spaceLayout.blocks.find((b) => b.type === op.block_type);
        if (block && op.size) {
          batchOps.push({ action: "resize", blockId: block.id, size: op.size as BlockSize });
        }
      } else if (op.action === "update_config") {
        const block = ws.spaceLayout.blocks.find((b) => b.type === op.block_type);
        if (block && op.config) {
          batchOps.push({ action: "update_config", blockId: block.id, config: op.config });
        }
      }
    }

    if (batchOps.length > 0) {
      ws.batchUpdateBlocks(batchOps);

      // Show adaptation toast with undo support
      try {
        const { showAdaptationToast } = await import("@/components/shared/adaptation-toast");
        showAdaptationToast(result.explanation, result.operations, () => ws.undoLayout());
      } catch {
        // Toast is best-effort
      }
    }
  } catch {
    // Best-effort
  }
}

/**
 * Categorize error messages for user-friendly display.
 */
export function categorizeError(
  msg: string,
): "rate_limit" | "auth_error" | "timeout" | "llm_unavailable" | "generic" {
  if (/rate.?limit|429/i.test(msg)) return "rate_limit";
  if (/auth|401|403|api.?key|unauthorized/i.test(msg)) return "auth_error";
  if (/timeout|timed?\s?out|abort/i.test(msg)) return "timeout";
  if (/llm|model|provider|mock|circuit/i.test(msg)) return "llm_unavailable";
  return "generic";
}
