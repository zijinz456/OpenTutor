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
    color: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800/50 dark:text-zinc-400",
  },
  add_to_quiz: {
    section: "practice",
    icon: ClipboardList,
    color: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800/50 dark:text-zinc-400",
  },
  open_plan: {
    section: "plan",
    icon: CalendarCheck,
    color: "bg-zinc-200 text-zinc-800 dark:bg-zinc-700/50 dark:text-zinc-300",
  },
  show_plan: {
    section: "plan",
    icon: CalendarCheck,
    color: "bg-zinc-200 text-zinc-800 dark:bg-zinc-700/50 dark:text-zinc-300",
  },
  open_notes: {
    section: "notes",
    icon: StickyNote,
    color: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800/50 dark:text-zinc-400",
  },
  add_to_notes: {
    section: "notes",
    icon: StickyNote,
    color: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800/50 dark:text-zinc-400",
  },
  open_section: {
    section: "notes",
    icon: BookOpen,
    color: "bg-zinc-200 text-zinc-800 dark:bg-zinc-700/50 dark:text-zinc-300",
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
      const VALID_SECTIONS: Set<string> = new Set(["notes", "practice", "analytics", "plan"]);
      // For switch_tab / open_section, use the label as target only if it's a valid SectionId.
      const target =
        action.type === "switch_tab" || action.type === "open_section"
          ? (VALID_SECTIONS.has(action.label ?? "") ? (action.label as SectionId) : mapping.section)
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
