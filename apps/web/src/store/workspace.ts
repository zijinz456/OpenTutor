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

  /** PDF viewer overlay (VS Code file-open pattern). */
  pdfOverlay: { fileId: string; fileName: string } | null;
  openPdf: (fileId: string, fileName: string) => void;
  closePdf: () => void;

  /** Left course-tree collapsed state. */
  treeCollapsed: boolean;
  toggleTree: () => void;

  /** Bottom chat panel height ratio (0–1, proportion of viewport). */
  chatHeight: number;
  setChatHeight: (h: number) => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  activeSection: "notes",
  setActiveSection: (id) => set({ activeSection: id, pdfOverlay: null }),

  pdfOverlay: null,
  openPdf: (fileId, fileName) => set({ pdfOverlay: { fileId, fileName } }),
  closePdf: () => set({ pdfOverlay: null }),

  treeCollapsed: false,
  toggleTree: () => set((s) => ({ treeCollapsed: !s.treeCollapsed })),

  chatHeight: 0.35,
  setChatHeight: (h) => set({ chatHeight: Math.max(0.15, Math.min(0.7, h)) }),
}));
