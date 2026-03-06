/**
 * Workspace state management using Zustand.
 *
 * Controls the VS-Code-style layout: active section, course-tree collapse,
 * PDF overlay, and bottom chat panel height.
 */

import { create } from "zustand";

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
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
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
}));
