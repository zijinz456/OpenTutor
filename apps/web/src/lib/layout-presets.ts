import type { SectionId } from "@/store/workspace";

export interface SectionLayout {
  type: SectionId;
  position: number;
  visible: boolean;
  size?: "small" | "medium" | "large";
}

export interface WorkspaceLayout {
  preset: string;
  sections: SectionLayout[];
  chat_visible: boolean;
  chat_height: number;
  tree_visible: boolean;
  tree_width: number;
}

export type PresetId = "focused" | "daily_study" | "exam_prep" | "assignment" | "minimal";

export const LAYOUT_PRESETS: Record<PresetId, WorkspaceLayout> = {
  focused: {
    preset: "focused",
    sections: [
      { type: "notes", position: 0, visible: false },
      { type: "practice", position: 1, visible: false },
      { type: "analytics", position: 2, visible: false },
      { type: "plan", position: 3, visible: false },
    ],
    chat_visible: true,
    chat_height: 0.65,
    tree_visible: true,
    tree_width: 260,
  },
  daily_study: {
    preset: "daily_study",
    sections: [
      { type: "notes", position: 0, visible: true, size: "large" },
      { type: "practice", position: 1, visible: true, size: "medium" },
      { type: "analytics", position: 2, visible: false },
      { type: "plan", position: 3, visible: false },
    ],
    chat_visible: true,
    chat_height: 0.35,
    tree_visible: true,
    tree_width: 240,
  },
  exam_prep: {
    preset: "exam_prep",
    sections: [
      { type: "notes", position: 0, visible: false },
      { type: "practice", position: 1, visible: true, size: "large" },
      { type: "analytics", position: 2, visible: true, size: "medium" },
      { type: "plan", position: 3, visible: true, size: "small" },
    ],
    chat_visible: true,
    chat_height: 0.25,
    tree_visible: true,
    tree_width: 200,
  },
  assignment: {
    preset: "assignment",
    sections: [
      { type: "notes", position: 0, visible: true, size: "medium" },
      { type: "practice", position: 1, visible: false },
      { type: "analytics", position: 2, visible: false },
      { type: "plan", position: 3, visible: true, size: "large" },
    ],
    chat_visible: true,
    chat_height: 0.35,
    tree_visible: true,
    tree_width: 240,
  },
  minimal: {
    preset: "minimal",
    sections: [
      { type: "notes", position: 0, visible: false },
      { type: "practice", position: 1, visible: false },
      { type: "analytics", position: 2, visible: false },
      { type: "plan", position: 3, visible: false },
    ],
    chat_visible: true,
    chat_height: 0.7,
    tree_visible: false,
    tree_width: 240,
  },
};

export const DEFAULT_LAYOUT: WorkspaceLayout = LAYOUT_PRESETS.focused;

export function getVisibleSections(layout: WorkspaceLayout): SectionId[] {
  return layout.sections
    .filter((s) => s.visible)
    .sort((a, b) => a.position - b.position)
    .map((s) => s.type);
}

export function toggleSection(layout: WorkspaceLayout, sectionId: SectionId, visible: boolean): WorkspaceLayout {
  return {
    ...layout,
    preset: "custom",
    sections: layout.sections.map((s) =>
      s.type === sectionId ? { ...s, visible } : s,
    ),
  };
}
