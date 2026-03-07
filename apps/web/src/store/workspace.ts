/**
 * Workspace state management using Zustand.
 *
 * Controls layout, block system, and agent autonomy state.
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
import type {
  BlockInstance,
  BlockType,
  BlockSize,
  BlockSource,
  AgentBlockMeta,
  SpaceLayout,
  LearningMode,
} from "@/lib/block-system/types";
import { buildLayoutFromTemplate, buildLayoutFromMode } from "@/lib/block-system/templates";
import { BLOCK_REGISTRY } from "@/lib/block-system/registry";

export type SectionId = "notes" | "practice" | "analytics" | "plan";

let blockIdCounter = 0;
function nextBlockId(): string {
  return `blk-${Date.now()}-${++blockIdCounter}`;
}

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

  /** Dynamic layout configuration (legacy). */
  layout: WorkspaceLayout;
  setLayout: (layout: WorkspaceLayout) => void;
  applyPreset: (presetId: PresetId) => void;
  toggleLayoutSection: (sectionId: SectionId, visible: boolean) => void;

  // ── Block System ──

  /** Block-based space layout. */
  spaceLayout: SpaceLayout;

  /** Add a block to the space. */
  addBlock: (type: BlockType, config?: Record<string, unknown>, source?: BlockSource) => void;

  /** Remove a block by ID. */
  removeBlock: (blockId: string) => void;

  /** Remove the first block matching a given type. */
  removeBlockByType: (type: BlockType) => void;

  /** Reorder blocks by providing an ordered list of types. */
  reorderBlocks: (orderedTypes: BlockType[]) => void;

  /** Resize a block. */
  resizeBlock: (blockId: string, size: BlockSize) => void;

  /** Update a block's config. */
  updateBlockConfig: (blockId: string, config: Record<string, unknown>) => void;

  /** Apply a template, replacing all blocks. */
  applyBlockTemplate: (templateId: string) => void;

  /** Agent adds a block with metadata (tier 1: auto, tier 2: needs approval). */
  agentAddBlock: (
    type: BlockType,
    config: Record<string, unknown>,
    meta: AgentBlockMeta,
  ) => void;

  /** User approves an agent-suggested block. */
  approveAgentBlock: (blockId: string) => void;

  /** User dismisses an agent block. */
  dismissAgentBlock: (blockId: string) => void;

  /** Load blocks from persisted state (e.g., course metadata). */
  loadBlocks: (layout: SpaceLayout) => void;

  /** Set learning mode and apply its default block layout. */
  setLearningMode: (mode: LearningMode) => void;
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

  // ── Block System ──

  spaceLayout: { templateId: null, blocks: [], columns: 2 },

  addBlock: (type, config = {}, source = "user") => {
    const entry = BLOCK_REGISTRY[type];
    if (!entry) return;
    const blocks = get().spaceLayout.blocks;
    const newBlock: BlockInstance = {
      id: nextBlockId(),
      type,
      position: blocks.length,
      size: entry.defaultSize,
      config: { ...entry.defaultConfig, ...config },
      visible: true,
      source,
    };
    set((s) => ({
      spaceLayout: {
        ...s.spaceLayout,
        blocks: [...s.spaceLayout.blocks, newBlock],
      },
    }));
  },

  removeBlock: (blockId) => {
    set((s) => ({
      spaceLayout: {
        ...s.spaceLayout,
        blocks: s.spaceLayout.blocks
          .filter((b) => b.id !== blockId)
          .map((b, i) => ({ ...b, position: i })),
      },
    }));
  },

  removeBlockByType: (type) => {
    set((s) => {
      const idx = s.spaceLayout.blocks.findIndex((b) => b.type === type);
      if (idx === -1) return s;
      const blocks = [...s.spaceLayout.blocks];
      blocks.splice(idx, 1);
      return {
        spaceLayout: {
          ...s.spaceLayout,
          blocks: blocks.map((b, i) => ({ ...b, position: i })),
        },
      };
    });
  },

  reorderBlocks: (orderedTypes) => {
    set((s) => {
      const blocksByType = new Map<BlockType, BlockInstance[]>();
      for (const b of s.spaceLayout.blocks) {
        const list = blocksByType.get(b.type) ?? [];
        list.push(b);
        blocksByType.set(b.type, list);
      }
      const reordered: BlockInstance[] = [];
      for (const type of orderedTypes) {
        const list = blocksByType.get(type);
        if (list?.length) {
          reordered.push(list.shift()!);
          if (list.length === 0) blocksByType.delete(type);
        }
      }
      // Append any blocks not in the ordered list
      for (const remaining of blocksByType.values()) {
        reordered.push(...remaining);
      }
      return {
        spaceLayout: {
          ...s.spaceLayout,
          blocks: reordered.map((b, i) => ({ ...b, position: i })),
        },
      };
    });
  },

  resizeBlock: (blockId, size) => {
    set((s) => ({
      spaceLayout: {
        ...s.spaceLayout,
        blocks: s.spaceLayout.blocks.map((b) =>
          b.id === blockId ? { ...b, size } : b,
        ),
      },
    }));
  },

  updateBlockConfig: (blockId, config) => {
    set((s) => ({
      spaceLayout: {
        ...s.spaceLayout,
        blocks: s.spaceLayout.blocks.map((b) =>
          b.id === blockId ? { ...b, config: { ...b.config, ...config } } : b,
        ),
      },
    }));
  },

  applyBlockTemplate: (templateId) => {
    const layout = buildLayoutFromTemplate(templateId);
    if (layout) {
      set({ spaceLayout: layout });
    }
  },

  agentAddBlock: (type, config, meta) => {
    const entry = BLOCK_REGISTRY[type];
    if (!entry) return;
    const blocks = get().spaceLayout.blocks;
    // For tier-1 (no approval needed), insert at a smart position
    // For tier-2 (needs approval), insert at the top so it's visible
    const position = meta.needsApproval ? 0 : blocks.length;
    const newBlock: BlockInstance = {
      id: nextBlockId(),
      type,
      position,
      size: entry.defaultSize,
      config: { ...entry.defaultConfig, ...config },
      visible: true,
      source: "agent",
      agentMeta: meta,
    };
    set((s) => {
      const allBlocks = meta.needsApproval
        ? [newBlock, ...s.spaceLayout.blocks]
        : [...s.spaceLayout.blocks, newBlock];
      return {
        spaceLayout: {
          ...s.spaceLayout,
          blocks: allBlocks.map((b, i) => ({ ...b, position: i })),
        },
      };
    });
  },

  approveAgentBlock: (blockId) => {
    set((s) => ({
      spaceLayout: {
        ...s.spaceLayout,
        blocks: s.spaceLayout.blocks.map((b) =>
          b.id === blockId && b.agentMeta
            ? { ...b, agentMeta: { ...b.agentMeta, needsApproval: false } }
            : b,
        ),
      },
    }));
  },

  dismissAgentBlock: (blockId) => {
    set((s) => ({
      spaceLayout: {
        ...s.spaceLayout,
        blocks: s.spaceLayout.blocks
          .filter((b) => b.id !== blockId)
          .map((b, i) => ({ ...b, position: i })),
      },
    }));
  },

  loadBlocks: (layout) => {
    set({ spaceLayout: layout });
  },

  setLearningMode: (mode) => {
    const layout = buildLayoutFromMode(mode);
    set({ spaceLayout: layout });
  },
}));
