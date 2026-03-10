/**
 * Chat streaming event handlers — extracted from chat store.
 */

import type { ChatAction, ChatMessageMetadata, ClarifyOption, PlanProgressEvent } from "@/lib/api";

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
 * Apply layout simplification from cognitive load analysis.
 * Best-effort: silently fails if workspace store isn't available.
 */
export async function applyLayoutSimplification(
  simplification: { should_simplify: boolean; blocks_to_hide: string[]; reason: string } | undefined,
): Promise<void> {
  if (!simplification?.should_simplify || !simplification.blocks_to_hide.length) return;
  try {
    const { useWorkspaceStore } = await import("@/store/workspace");
    const ws = useWorkspaceStore.getState();
    const ops = simplification.blocks_to_hide
      .map((type: string) => {
        const block = ws.spaceLayout.blocks.find((b) => b.type === type);
        return block ? { action: "remove" as const, blockId: block.id } : null;
      })
      .filter(Boolean) as Array<{ action: "remove"; blockId: string }>;
    if (ops.length > 0) {
      ws.batchUpdateBlocks(ops);
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
