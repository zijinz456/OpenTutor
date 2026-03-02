import type { SectionId } from "@/store/workspace";

export interface SectionMeta {
  id: SectionId;
  label: string;
  labelZh: string;
  icon: string;
  shortcut: string;
}

export const SECTIONS: SectionMeta[] = [
  { id: "notes", label: "Notes", labelZh: "笔记", icon: "FileText", shortcut: "1" },
  { id: "practice", label: "Practice", labelZh: "练习", icon: "Dumbbell", shortcut: "2" },
  { id: "analytics", label: "Analytics", labelZh: "分析", icon: "BarChart3", shortcut: "3" },
  { id: "plan", label: "Plan", labelZh: "计划", icon: "CalendarCheck", shortcut: "4" },
] as const;

/** Map section id → meta for quick lookup. */
export const SECTION_MAP = Object.fromEntries(
  SECTIONS.map((s) => [s.id, s]),
) as Record<SectionId, SectionMeta>;

/** Course tree default width (px). */
export const TREE_WIDTH = 240;

/** Course tree collapsed width (px) — enough for the expand icon. */
export const TREE_COLLAPSED_WIDTH = 40;

/** Minimum chat panel height ratio. */
export const CHAT_MIN_HEIGHT = 0.15;

/** Maximum chat panel height ratio. */
export const CHAT_MAX_HEIGHT = 0.7;

/** Default chat panel height ratio. */
export const CHAT_DEFAULT_HEIGHT = 0.35;
