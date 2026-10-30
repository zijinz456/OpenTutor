/**
 * Workspace state management using Zustand.
 *
 * Controls selection, section refresh signals and block-system state.
 * Block system operations are extracted to workspace-blocks.ts.
 */

import { create } from "zustand";
import type { CognitiveState } from "@/lib/api";
import { type BlockSystemState, createBlockSlice } from "./workspace-blocks";

/** Workspace sections that can be refreshed by chat actions. */
export type SectionId = "notes" | "practice" | "analytics" | "plan";

interface CoreWorkspaceState {
  selectedNodeId: string | null;
  setSelectedNodeId: (id: string | null) => void;
  sectionRefreshKey: Record<SectionId, number>;
  triggerRefresh: (section: SectionId) => void;
  practiceActiveTab: string | null;
  setPracticeTab: (tab: string | null) => void;
  /** Latest cognitive state from the Block Decision Engine. */
  cognitiveState: CognitiveState | null;
  setCognitiveState: (state: CognitiveState) => void;

  /** Notes drawer open state (right-side panel). */
  notesDrawerOpen: boolean;
  setNotesDrawerOpen: (open: boolean) => void;
}

type WorkspaceState = CoreWorkspaceState & BlockSystemState;

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  selectedNodeId: null,
  setSelectedNodeId: (id) => set({ selectedNodeId: id }),

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

  cognitiveState: null,
  setCognitiveState: (state) => set({ cognitiveState: state }),

  notesDrawerOpen: false,
  setNotesDrawerOpen: (open) => set({ notesDrawerOpen: open }),

  // Block system (extracted to workspace-blocks.ts)
  ...createBlockSlice(set, get),
}));
