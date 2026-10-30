"use client";

import { useRouter, useParams } from "next/navigation";
import { useWorkspaceStore } from "@/store/workspace";
import { cn } from "@/lib/utils";
import {
  LayoutGrid,
  RefreshCw,
  Sparkles,
  Focus,
  ArrowRight,
} from "lucide-react";

interface ActionCardProps {
  action: {
    type: string;
    label?: string;
    payload?: Record<string, unknown>;
  };
}

/** Route (relative to the course) each action type opens, plus its icon. */
const ACTION_MAP: Record<
  string,
  { path: string; icon: typeof ArrowRight; color: string }
> = {
  data_updated: { path: "", icon: RefreshCw, color: "bg-muted/30 text-muted-foreground" },
  focus_topic: { path: "/notes", icon: Focus, color: "bg-muted/30 text-muted-foreground" },
  add_block: { path: "", icon: LayoutGrid, color: "bg-muted/40 text-foreground/80" },
  remove_block: { path: "", icon: LayoutGrid, color: "bg-muted/40 text-foreground/80" },
  reorder_blocks: { path: "", icon: LayoutGrid, color: "bg-muted/40 text-foreground/80" },
  resize_block: { path: "", icon: LayoutGrid, color: "bg-muted/40 text-foreground/80" },
  apply_template: { path: "", icon: LayoutGrid, color: "bg-muted/40 text-foreground/80" },
  agent_insight: { path: "", icon: Sparkles, color: "bg-muted/40 text-foreground/80" },
  set_learning_mode: { path: "/plan", icon: Sparkles, color: "bg-muted/40 text-foreground/80" },
  suggest_mode: { path: "/plan", icon: Sparkles, color: "bg-muted/40 text-foreground/80" },
  unknown: { path: "", icon: ArrowRight, color: "bg-muted/30 text-muted-foreground" },
};

/** `data_updated` labels name the section that changed; map to its route. */
const SECTION_PATHS: Record<string, string> = {
  notes: "/notes",
  practice: "/practice",
  analytics: "/profile",
  plan: "/plan",
};

/**
 * Small clickable pill/badge rendered inside assistant message bubbles.
 * Navigates to the dedicated route the action refers to.
 */
export function ActionCard({ action }: ActionCardProps) {
  const router = useRouter();
  const params = useParams();
  const courseId = (params?.id as string) ?? "";
  const setSelectedNodeId = useWorkspaceStore((s) => s.setSelectedNodeId);

  const mapping = ACTION_MAP[action.type] ?? ACTION_MAP.unknown;
  const Icon = mapping.icon;

  const handleClick = () => {
    if (!courseId) return;
    if (action.type === "focus_topic" && action.label) {
      setSelectedNodeId(action.label);
      router.push(`/course/${courseId}/unit/${action.label}`);
      return;
    }
    const sectionPath = action.type === "data_updated" ? SECTION_PATHS[action.label ?? ""] : undefined;
    router.push(`/course/${courseId}${sectionPath ?? mapping.path}`);
  };

  const label =
    action.label ?? action.type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-label={`Action: ${label}`}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium card-shadow",
        "transition-all hover:opacity-80 active:opacity-60",
        "cursor-pointer select-none",
        mapping.color,
      )}
    >
      <Icon className="size-3" aria-hidden="true" />
      <span>{label}</span>
    </button>
  );
}
