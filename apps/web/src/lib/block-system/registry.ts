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
  label: string;
  labelZh: string;
  icon: string;
  description: string;
  defaultSize: BlockSize;
  defaultConfig: Record<string, unknown>;
  component: LazyExoticComponent<ComponentType<BlockComponentProps>>;
}

const entry = (
  type: BlockType,
  label: string,
  labelZh: string,
  icon: string,
  description: string,
  defaultSize: BlockSize,
  defaultConfig: Record<string, unknown>,
  loader: () => Promise<{ default: ComponentType<BlockComponentProps> }>,
): BlockRegistryEntry => ({
  type,
  label,
  labelZh,
  icon,
  description,
  defaultSize,
  defaultConfig,
  component: lazy(loader),
});

export const BLOCK_REGISTRY: Record<BlockType, BlockRegistryEntry> = {
  chapter_list: entry(
    "chapter_list", "Chapters", "章节目录", "BookOpen",
    "Course content outline",
    "full", {},
    () => import("@/components/blocks/blocks/chapter-list-block"),
  ),
  notes: entry(
    "notes", "Notes", "笔记", "FileText",
    "AI-generated study notes",
    "large", {},
    () => import("@/components/blocks/blocks/notes-block"),
  ),
  quiz: entry(
    "quiz", "Quiz", "测验", "CircleHelp",
    "Practice questions and quizzes",
    "medium", { difficulty: "adaptive" },
    () => import("@/components/blocks/blocks/quiz-block"),
  ),
  flashcards: entry(
    "flashcards", "Flashcards", "闪卡", "Layers",
    "Spaced repetition flashcards",
    "medium", {},
    () => import("@/components/blocks/blocks/flashcards-block"),
  ),
  progress: entry(
    "progress", "Progress", "学习进度", "BarChart3",
    "Mastery and completion stats",
    "small", {},
    () => import("@/components/blocks/blocks/progress-block"),
  ),
  knowledge_graph: entry(
    "knowledge_graph", "Knowledge Graph", "知识图谱", "GitBranch",
    "LOOM concept relationship map",
    "medium", {},
    () => import("@/components/blocks/blocks/knowledge-graph-block"),
  ),
  review: entry(
    "review", "Review", "复习", "RotateCcw",
    "LECTOR-driven spaced review",
    "medium", {},
    () => import("@/components/blocks/blocks/review-block"),
  ),
  plan: entry(
    "plan", "Study Plan", "学习计划", "CalendarDays",
    "Goals, tasks, and deadlines",
    "medium", {},
    () => import("@/components/blocks/blocks/plan-block"),
  ),
  wrong_answers: entry(
    "wrong_answers", "Weak Spots", "薄弱点", "AlertTriangle",
    "Error patterns and misconceptions",
    "medium", {},
    () => import("@/components/blocks/blocks/wrong-answers-block"),
  ),
  forecast: entry(
    "forecast", "Forecast", "预测", "TrendingUp",
    "Learning trajectory forecast",
    "small", {},
    () => import("@/components/blocks/blocks/forecast-block"),
  ),
  agent_insight: entry(
    "agent_insight", "Agent Insight", "助手洞察", "Sparkles",
    "Proactive suggestions from your AI tutor",
    "full", {},
    () => import("@/components/blocks/blocks/agent-insight-block"),
  ),
  summary: entry(
    "summary", "Daily Digest", "学习摘要", "Newspaper",
    "Today's learning snapshot: mastery, quiz accuracy, review due",
    "small", {},
    () => import("@/components/blocks/blocks/summary-block"),
  ),
};

/** Block types available for user to add manually (excludes agent_insight) */
export const USER_ADDABLE_BLOCKS: BlockType[] = [
  "notes", "quiz", "flashcards", "review", "plan",
  "knowledge_graph", "progress", "wrong_answers", "forecast", "summary",
];
