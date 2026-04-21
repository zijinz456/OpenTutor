import { storage } from "@/lib/storage";
import type {
  AgentBlockMeta,
  BlockInstance,
  BlockSize,
  BlockSource,
  BlockType,
  LearningMode,
  SpaceLayout,
} from "./types";

const BLOCK_TYPES: readonly BlockType[] = [
  "notes",
  "quiz",
  "flashcards",
  "progress",
  "knowledge_graph",
  "review",
  "chapter_list",
  "plan",
  "wrong_answers",
  "forecast",
  "agent_insight",
] as const;

const BLOCK_SIZES: readonly BlockSize[] = ["small", "medium", "large", "full"] as const;
const BLOCK_SOURCES: readonly BlockSource[] = ["template", "user", "agent"] as const;
const LEARNING_MODES: readonly LearningMode[] = [
  "course_following",
  "self_paced",
  "exam_prep",
  "maintenance",
] as const;

const BLOCK_DEFAULT_SIZES: Record<BlockType, BlockSize> = {
  chapter_list: "full",
  notes: "large",
  quiz: "medium",
  flashcards: "medium",
  progress: "small",
  knowledge_graph: "medium",
  review: "medium",
  plan: "medium",
  wrong_answers: "medium",
  forecast: "small",
  agent_insight: "full",
  summary: "medium",
};

let fallbackBlockIdCounter = 0;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isBlockType(value: unknown): value is BlockType {
  return typeof value === "string" && BLOCK_TYPES.includes(value as BlockType);
}

function isBlockSize(value: unknown): value is BlockSize {
  return typeof value === "string" && BLOCK_SIZES.includes(value as BlockSize);
}

function isBlockSource(value: unknown): value is BlockSource {
  return typeof value === "string" && BLOCK_SOURCES.includes(value as BlockSource);
}

export function isLearningMode(value: unknown): value is LearningMode {
  return typeof value === "string" && LEARNING_MODES.includes(value as LearningMode);
}

export function createBlockId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return `blk-${globalThis.crypto.randomUUID()}`;
  }
  fallbackBlockIdCounter += 1;
  return `blk-fallback-${Date.now()}-${fallbackBlockIdCounter}`;
}

function sanitizeAgentMeta(value: unknown): AgentBlockMeta | undefined {
  if (!isRecord(value)) return undefined;

  const meta: AgentBlockMeta = {
    reason: typeof value.reason === "string" ? value.reason : "",
    dismissible: typeof value.dismissible === "boolean" ? value.dismissible : true,
  };

  if (typeof value.expiresAt === "string" && value.expiresAt.trim()) {
    meta.expiresAt = value.expiresAt;
  }
  if (typeof value.needsApproval === "boolean") {
    meta.needsApproval = value.needsApproval;
  }
  if (typeof value.approvalCta === "string" && value.approvalCta.trim()) {
    meta.approvalCta = value.approvalCta;
  }

  return meta;
}

function sanitizeBlock(
  value: unknown,
  index: number,
  seenIds: Set<string>,
): BlockInstance | null {
  if (!isRecord(value) || !isBlockType(value.type)) return null;

  const type = value.type;
  const rawId = typeof value.id === "string" ? value.id.trim() : "";
  const id = rawId && !seenIds.has(rawId) ? rawId : createBlockId();
  seenIds.add(id);

  return {
    id,
    type,
    position: Number.isFinite(value.position) ? Number(value.position) : index,
    size: isBlockSize(value.size) ? value.size : BLOCK_DEFAULT_SIZES[type],
    config: isRecord(value.config) ? value.config : {},
    visible: typeof value.visible === "boolean" ? value.visible : true,
    source: isBlockSource(value.source) ? value.source : "user",
    agentMeta: sanitizeAgentMeta(value.agentMeta),
  };
}

export function parseSpaceLayout(value: unknown): SpaceLayout | null {
  if (!isRecord(value) || !Array.isArray(value.blocks)) return null;

  const seenIds = new Set<string>();
  const blocks = value.blocks
    .map((block, index) => sanitizeBlock(block, index, seenIds))
    .filter((block): block is BlockInstance => block !== null)
    .sort((a, b) => a.position - b.position)
    .map((block, index) => ({ ...block, position: index }));

  const layout: SpaceLayout = {
    templateId:
      typeof value.templateId === "string" && value.templateId.trim()
        ? value.templateId
        : null,
    blocks,
    columns:
      value.columns === 1 || value.columns === 2 || value.columns === 3
        ? value.columns
        : 2,
  };

  if (isLearningMode(value.mode)) {
    layout.mode = value.mode;
  }

  return layout;
}

export function normalizeSpaceLayout(value: SpaceLayout): SpaceLayout {
  return parseSpaceLayout(value) ?? { templateId: null, blocks: [], columns: 2 };
}

export function getSpaceLayoutStorageKey(courseId: string): string {
  return `opentutor_blocks_${courseId}`;
}

export function loadStoredSpaceLayout(courseId: string): SpaceLayout | null {
  const raw = storage.getRaw(getSpaceLayoutStorageKey(courseId));
  if (!raw) return null;

  try {
    return parseSpaceLayout(JSON.parse(raw));
  } catch {
    return null;
  }
}

export function saveStoredSpaceLayout(courseId: string, layout: SpaceLayout): SpaceLayout {
  const normalized = normalizeSpaceLayout(layout);
  storage.set(getSpaceLayoutStorageKey(courseId), normalized);
  return normalized;
}

export function getStoredSpaceLayoutMode(courseId: string): LearningMode | undefined {
  return loadStoredSpaceLayout(courseId)?.mode;
}
