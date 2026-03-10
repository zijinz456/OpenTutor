/**
 * Workspace state management using Zustand.
 *
 * Controls layout, block system, and agent autonomy state.
 * Block system operations extracted to workspace-blocks.ts.
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
import type { CognitiveState } from "@/lib/api";
import { type BlockSystemState, createBlockSlice } from "./workspace-blocks";

export type SectionId = "notes" | "practice" | "analytics" | "plan";

interface CoreWorkspaceState {
  activeSection: SectionId;
  setActiveSection: (id: SectionId) => void;
  selectedNodeId: string | null;
  setSelectedNodeId: (id: string | null) => void;
  pdfOverlay: { fileId: string; fileName: string } | null;
  openPdf: (fileId: string, fileName: string) => void;
  closePdf: () => void;
  treeCollapsed: boolean;
  toggleTree: () => void;
  treeWidth: number;
  setTreeWidth: (w: number) => void;
  chatHeight: number;
  setChatHeight: (h: number) => void;
  sectionRefreshKey: Record<string, number>;
  triggerRefresh: (section: SectionId) => void;
  practiceActiveTab: string | null;
  setPracticeTab: (tab: string | null) => void;
  layout: WorkspaceLayout;
  setLayout: (layout: WorkspaceLayout) => void;
  applyPreset: (presetId: PresetId) => void;
  toggleLayoutSection: (sectionId: SectionId, visible: boolean) => void;
  /** Latest cognitive state from the Block Decision Engine. */
  cognitiveState: CognitiveState | null;
  setCognitiveState: (state: CognitiveState) => void;
}

type WorkspaceState = CoreWorkspaceState & BlockSystemState;

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

  cognitiveState: null,
  setCognitiveState: (state) => set({ cognitiveState: state }),

  // Block system (extracted to workspace-blocks.ts)
  ...createBlockSlice(set, get),
}));
