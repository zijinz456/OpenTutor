import { lazy, type ComponentType, type LazyExoticComponent } from "react";
import type { BlockType, BlockSize } from "./types";

export interface BlockComponentProps {
  courseId: string;
  blockId: string;
  config: Record<string, unknown>;
  aiActionsEnabled: boolean;
}

export interface BlockRegistryEntry {
  type: BlockType;
  /** Locale key for the block label (`blocks.<type>.label`). */
  labelKey: string;
  icon: string;
  /** Locale key for the block description (`blocks.<type>.description`). */
  descriptionKey: string;
  defaultSize: BlockSize;
  defaultConfig: Record<string, unknown>;
  component: LazyExoticComponent<ComponentType<BlockComponentProps>>;
}

const entry = (
  type: BlockType,
  icon: string,
  defaultSize: BlockSize,
  defaultConfig: Record<string, unknown>,
  loader: () => Promise<{ default: ComponentType<BlockComponentProps> }>,
): BlockRegistryEntry => ({
  type,
  labelKey: `blocks.${type}.label`,
  icon,
  descriptionKey: `blocks.${type}.description`,
  defaultSize,
  defaultConfig,
  component: lazy(loader),
});

export const BLOCK_REGISTRY: Record<BlockType, BlockRegistryEntry> = {
  chapter_list: entry(
    "chapter_list", "BookOpen",
    "full", {},
    () => import("@/components/blocks/blocks/chapter-list-block"),
  ),
  notes: entry(
    "notes", "FileText",
    "large", {},
    () => import("@/components/blocks/blocks/notes-block"),
  ),
  quiz: entry(
    "quiz", "CircleHelp",
    "medium", { difficulty: "adaptive" },
    () => import("@/components/blocks/blocks/quiz-block"),
  ),
  flashcards: entry(
    "flashcards", "Layers",
    "medium", {},
    () => import("@/components/blocks/blocks/flashcards-block"),
  ),
  progress: entry(
    "progress", "BarChart3",
    "small", {},
    () => import("@/components/blocks/blocks/progress-block"),
  ),
  knowledge_graph: entry(
    "knowledge_graph", "GitBranch",
    "medium", {},
    () => import("@/components/blocks/blocks/knowledge-graph-block"),
  ),
  review: entry(
    "review", "RotateCcw",
    "medium", {},
    () => import("@/components/blocks/blocks/review-block"),
  ),
  plan: entry(
    "plan", "CalendarDays",
    "medium", {},
    () => import("@/components/blocks/blocks/plan-block"),
  ),
  wrong_answers: entry(
    "wrong_answers", "AlertTriangle",
    "medium", {},
    () => import("@/components/blocks/blocks/wrong-answers-block"),
  ),
  forecast: entry(
    "forecast", "TrendingUp",
    "small", {},
    () => import("@/components/blocks/blocks/forecast-block"),
  ),
  agent_insight: entry(
    "agent_insight", "Sparkles",
    "full", {},
    () => import("@/components/blocks/blocks/agent-insight-block"),
  ),
  summary: entry(
    "summary", "Newspaper",
    "small", {},
    () => import("@/components/blocks/blocks/summary-block"),
  ),
};

/** Block types available for user to add manually (excludes agent_insight) */
export const USER_ADDABLE_BLOCKS: BlockType[] = [
  "notes", "quiz", "flashcards", "review", "plan",
  "knowledge_graph", "progress", "wrong_answers", "forecast", "summary",
];
