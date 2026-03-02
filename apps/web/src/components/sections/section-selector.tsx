"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SECTIONS } from "@/lib/constants";
import { useLocale } from "@/lib/i18n-context";
import { useWorkspaceStore, type SectionId } from "@/store/workspace";
import {
  FileText,
  Dumbbell,
  BarChart3,
  CalendarCheck,
  type LucideIcon,
} from "lucide-react";

/** Map icon name from constants → lucide component. */
const ICON_MAP: Record<string, LucideIcon> = {
  FileText,
  Dumbbell,
  BarChart3,
  CalendarCheck,
};

/**
 * Section dropdown selector.
 *
 * Reads the active section from the workspace store and renders a compact
 * Select dropdown in the section header bar. Each item shows its icon, label,
 * and keyboard shortcut hint.
 */
export function SectionSelector() {
  const activeSection = useWorkspaceStore((s) => s.activeSection);
  const setActiveSection = useWorkspaceStore((s) => s.setActiveSection);
  const { locale } = useLocale();

  return (
    <Select
      value={activeSection}
      onValueChange={(v) => setActiveSection(v as SectionId)}
    >
      <SelectTrigger size="sm" className="h-7 gap-1.5 text-xs font-medium border-none shadow-none bg-transparent px-2">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {SECTIONS.map((section) => {
          const Icon = ICON_MAP[section.icon];
          return (
            <SelectItem key={section.id} value={section.id}>
              <span className="flex items-center gap-2">
                {Icon && <Icon className="size-3.5 text-muted-foreground" />}
                <span>{locale === "zh" ? section.labelZh : section.label}</span>
                <kbd className="ml-auto text-[10px] text-muted-foreground/60 font-mono">
                  {"\u2318"}{section.shortcut}
                </kbd>
              </span>
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
  );
}
