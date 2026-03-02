import type { ComponentType } from "react";
import {
  BookOpen,
  Layers,
  BarChart3,
  Network,
  ClipboardCheck,
  CalendarDays,
  BrainCircuit,
} from "lucide-react";

export const LAYOUT_PRESETS = {
  balanced: { pdf: 25, notes: 25, quiz: 25, chat: 25 },
  notesFocused: { pdf: 15, notes: 45, quiz: 20, chat: 20 },
  quizFocused: { pdf: 15, notes: 15, quiz: 50, chat: 20 },
  chatFocused: { pdf: 15, notes: 15, quiz: 15, chat: 55 },
  fullNotes: { pdf: 10, notes: 70, quiz: 10, chat: 10 },
} as const;

export const RIGHT_TAB_TYPES = ["quiz", "flashcards", "progress", "graph", "review", "plan", "activity", "profile"] as const;

export type LayoutPreset = keyof typeof LAYOUT_PRESETS;
export type RightTab = (typeof RIGHT_TAB_TYPES)[number];
export type HiddenPanelId = "pdf" | "notes" | "quiz" | "chat";

export const RIGHT_TAB_META: Record<RightTab, { label: string; icon: ComponentType<{ className?: string }> }> = {
  quiz: { label: "Quiz", icon: BookOpen },
  flashcards: { label: "Cards", icon: Layers },
  progress: { label: "Stats", icon: BarChart3 },
  graph: { label: "Graph", icon: Network },
  review: { label: "Review", icon: ClipboardCheck },
  plan: { label: "Plan", icon: CalendarDays },
  activity: { label: "Activity", icon: Layers },
  profile: { label: "Profile", icon: BrainCircuit },
};

export function isRightTab(value: string): value is RightTab {
  return RIGHT_TAB_TYPES.includes(value as RightTab);
}

export function getActivityItemForRightTab(tab: RightTab): string {
  if (tab === "progress" || tab === "graph") return "progress";
  if (tab === "plan") return "chat";
  if (tab === "activity") return "activity";
  if (tab === "profile") return "profile";
  return "practice";
}
