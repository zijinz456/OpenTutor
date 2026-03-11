/**
 * Chat streaming event handlers — extracted from chat store.
 */

import type { ChatAction, ChatMessageMetadata, ClarifyOption, PlanProgressEvent, BlockUpdateOp, CognitiveState } from "@/lib/api";
import type { BlockType, BlockSize } from "@/lib/block-system/types";
import { BLOCK_REGISTRY } from "@/lib/block-system/registry";

function isValidBlockType(type: string): type is BlockType {
  return type in BLOCK_REGISTRY;
}

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
  result: { operations: BlockUpdateOp[]; cognitiveState: CognitiveState; explanation: string; interventionIds?: Record<string, string> },
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
      if (!isValidBlockType(op.block_type)) {
        console.warn(`[BlockDecisions] Unknown block type: ${op.block_type}`);
        continue;
      }
      const blockType = op.block_type;

      if (op.action === "add") {
        batchOps.push({
          action: "add",
          type: blockType,
          config: op.config,
          size: op.size as BlockSize | undefined,
        });
      } else if (op.action === "remove") {
        const block = ws.spaceLayout.blocks.find((b) => b.type === blockType);
        if (block) {
          batchOps.push({ action: "remove", blockId: block.id });
        } else {
          console.debug(`[BlockDecisions] Cannot remove absent block: ${blockType}`);
        }
      } else if (op.action === "resize") {
        const block = ws.spaceLayout.blocks.find((b) => b.type === blockType);
        if (block && op.size) {
          batchOps.push({ action: "resize", blockId: block.id, size: op.size as BlockSize });
        } else {
          console.debug(`[BlockDecisions] Cannot resize absent block: ${blockType}`);
        }
      } else if (op.action === "update_config") {
        const block = ws.spaceLayout.blocks.find((b) => b.type === blockType);
        if (block && op.config) {
          batchOps.push({ action: "update_config", blockId: block.id, config: op.config });
        } else {
          console.debug(`[BlockDecisions] Cannot update absent block: ${blockType}`);
        }
      }
    }

    if (batchOps.length > 0) {
      ws.batchUpdateBlocks(batchOps);

      // Show adaptation toast with undo support
      try {
        const { showAdaptationToast } = await import("@/components/shared/adaptation-toast");
        showAdaptationToast(result.explanation, result.operations, () => ws.undoLayout(), result.interventionIds);
      } catch (e) {
        console.warn("[BlockDecisions] Toast notification failed:", e);
      }
    }
  } catch (e) {
    console.error("[BlockDecisions] Failed to apply block decisions:", e);
  }
}

/**
 * Categorize errors for user-friendly display.
 *
 * Prefers structured error codes from ApiError when available,
 * falling back to regex on the message string for SSE/network errors.
 */
export function categorizeError(
  error: unknown,
): "rate_limit" | "auth_error" | "timeout" | "llm_unavailable" | "generic" {
  // Structured path — use error code / HTTP status when available
  if (error && typeof error === "object") {
    const e = error as { code?: string; status?: number };
    if (e.code === "rate_limit_exceeded" || e.status === 429) return "rate_limit";
    if (e.code === "authentication_error" || e.code === "permission_denied" || e.status === 401 || e.status === 403) return "auth_error";
    if (e.code === "timeout_error" || e.status === 504) return "timeout";
    if (e.code === "llm_unavailable" || e.status === 503) return "llm_unavailable";
  }

  // Fallback — regex on message string (for SSE errors / plain Error objects)
  const msg = error instanceof Error ? error.message : String(error ?? "");
  if (/rate.?limit|429/i.test(msg)) return "rate_limit";
  if (/auth|401|403|api.?key|unauthorized/i.test(msg)) return "auth_error";
  if (/timeout|timed?\s?out|abort/i.test(msg)) return "timeout";
  if (/llm|model|provider|mock|circuit/i.test(msg)) return "llm_unavailable";
  return "generic";
}
