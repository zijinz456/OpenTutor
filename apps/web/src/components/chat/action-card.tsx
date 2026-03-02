"use client";

import { useWorkspaceStore, type SectionId } from "@/store/workspace";
import { cn } from "@/lib/utils";
import {
  BookOpen,
  ClipboardList,
  CalendarCheck,
  StickyNote,
  ArrowRight,
} from "lucide-react";

interface ActionCardProps {
  action: {
    type: string;
    label?: string;
    payload?: Record<string, unknown>;
  };
}

/** Map action types to their target workspace section and icon. */
const ACTION_MAP: Record<
  string,
  { section: SectionId; icon: typeof BookOpen; color: string }
> = {
  open_quiz: {
    section: "practice",
    icon: ClipboardList,
    color: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
  },
  add_to_quiz: {
    section: "practice",
    icon: ClipboardList,
    color: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
  },
  open_plan: {
    section: "plan",
    icon: CalendarCheck,
    color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  },
  show_plan: {
    section: "plan",
    icon: CalendarCheck,
    color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  },
  open_notes: {
    section: "notes",
    icon: StickyNote,
    color: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
  },
  add_to_notes: {
    section: "notes",
    icon: StickyNote,
    color: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
  },
  open_section: {
    section: "notes",
    icon: BookOpen,
    color: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
  },
  switch_tab: {
    section: "notes",
    icon: ArrowRight,
    color: "bg-gray-100 text-gray-700 dark:bg-gray-800/50 dark:text-gray-400",
  },
};

/**
 * Small clickable pill/badge rendered inside assistant message bubbles.
 * Dispatches to the workspace store on click to switch sections.
 */
export function ActionCard({ action }: ActionCardProps) {
  const setActiveSection = useWorkspaceStore((s) => s.setActiveSection);

  const mapping = ACTION_MAP[action.type];
  const Icon = mapping?.icon ?? ArrowRight;
  const colorClass =
    mapping?.color ??
    "bg-gray-100 text-gray-700 dark:bg-gray-800/50 dark:text-gray-400";

  const handleClick = () => {
    if (mapping) {
      // For switch_tab / open_section, use the label as the target section when possible.
      const target =
        action.type === "switch_tab" || action.type === "open_section"
          ? (action.label as SectionId) ?? mapping.section
          : mapping.section;
      setActiveSection(target);
    }
  };

  const label =
    action.label ?? action.type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  return (
    <button
      type="button"
      onClick={handleClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
        "transition-opacity hover:opacity-80 active:opacity-60",
        "cursor-pointer select-none",
        colorClass,
      )}
    >
      <Icon className="size-3" />
      <span>{label}</span>
    </button>
  );
}
