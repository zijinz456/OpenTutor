/**
 * Workspace state management using Zustand.
 *
 * Controls the VS-Code-style layout: active section, course-tree collapse,
 * PDF overlay, and bottom chat panel height.
 */

import { create } from "zustand";
import {
  type WorkspaceLayout,
  type PresetId,
  DEFAULT_LAYOUT,
  LAYOUT_PRESETS,
  getVisibleSections,
  toggleSection,
} from "@/lib/layout-presets";

export type SectionId = "notes" | "practice" | "analytics" | "plan";

interface WorkspaceState {
  /** Currently visible right-side section. */
  activeSection: SectionId;
  setActiveSection: (id: SectionId) => void;

  /** Currently selected content node in the tree. */
  selectedNodeId: string | null;
  setSelectedNodeId: (id: string | null) => void;

  /** PDF viewer overlay (VS Code file-open pattern). */
  pdfOverlay: { fileId: string; fileName: string } | null;
  openPdf: (fileId: string, fileName: string) => void;
  closePdf: () => void;

  /** Left course-tree collapsed state. */
  treeCollapsed: boolean;
  toggleTree: () => void;

  /** Left course-tree width in pixels. */
  treeWidth: number;
  setTreeWidth: (w: number) => void;

  /** Bottom chat panel height ratio (0–1, proportion of viewport). */
  chatHeight: number;
  setChatHeight: (h: number) => void;

  /** Per-section refresh counter — incremented by agent tools to trigger re-fetch. */
  sectionRefreshKey: Record<string, number>;
  triggerRefresh: (section: SectionId) => void;

  /** Agent-driven sub-tab hint for the practice section (consumed once on render). */
  practiceActiveTab: string | null;
  setPracticeTab: (tab: string | null) => void;

  /** Dynamic layout configuration. */
  layout: WorkspaceLayout;
  setLayout: (layout: WorkspaceLayout) => void;
  applyPreset: (presetId: PresetId) => void;
  toggleLayoutSection: (sectionId: SectionId, visible: boolean) => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  activeSection: "notes",
  setActiveSection: (id) => set({ activeSection: id, pdfOverlay: null }),

  selectedNodeId: null,
  setSelectedNodeId: (id) => set({ selectedNodeId: id }),

  pdfOverlay: null,
  openPdf: (fileId, fileName) => set({ pdfOverlay: { fileId, fileName } }),
  closePdf: () => set({ pdfOverlay: null }),

  treeCollapsed: false,
  toggleTree: () => set((s) => ({ treeCollapsed: !s.treeCollapsed })),

  treeWidth: 240,
  setTreeWidth: (w) => set({ treeWidth: Math.max(140, Math.min(480, w)) }),

  chatHeight: 0.35,
  setChatHeight: (h) => set({ chatHeight: Math.max(0.15, Math.min(0.7, h)) }),

  sectionRefreshKey: { notes: 0, practice: 0, analytics: 0, plan: 0 },
  triggerRefresh: (section) =>
    set((s) => ({
      sectionRefreshKey: {
        ...s.sectionRefreshKey,
        [section]: (s.sectionRefreshKey[section] ?? 0) + 1,
      },
    })),

  practiceActiveTab: null,
  setPracticeTab: (tab) => set({ practiceActiveTab: tab }),

  layout: DEFAULT_LAYOUT,
  setLayout: (layout) => {
    const visible = getVisibleSections(layout);
    const activeSection = get().activeSection;
    const nextActive = visible.includes(activeSection) ? activeSection : visible[0] ?? "notes";
    set({
      layout,
      treeWidth: layout.tree_width,
      treeCollapsed: !layout.tree_visible,
      chatHeight: layout.chat_height,
      activeSection: nextActive,
    });
  },
  applyPreset: (presetId) => {
    const preset = LAYOUT_PRESETS[presetId];
    if (preset) get().setLayout(preset);
  },
  toggleLayoutSection: (sectionId, visible) => {
    const next = toggleSection(get().layout, sectionId, visible);
    get().setLayout(next);
  },
}));
