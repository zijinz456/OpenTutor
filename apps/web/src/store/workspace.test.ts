import { describe, it, expect, beforeEach } from "vitest";
import { useWorkspaceStore } from "./workspace";

describe("useWorkspaceStore", () => {
  beforeEach(() => {
    // Reset store to initial state
    useWorkspaceStore.setState({
      activeSection: "notes",
      selectedNodeId: null,
      treeCollapsed: false,
      treeWidth: 240,
      chatHeight: 0.35,
      practiceActiveTab: null,
      spaceLayout: { templateId: null, blocks: [], columns: 2 },
      layoutHistory: [],
      lastRemovedBlock: null,
    });
  });

  describe("activeSection", () => {
    it("defaults to notes", () => {
      expect(useWorkspaceStore.getState().activeSection).toBe("notes");
    });

    it("can be changed", () => {
      useWorkspaceStore.getState().setActiveSection("practice");
      expect(useWorkspaceStore.getState().activeSection).toBe("practice");
    });
  });

  describe("tree controls", () => {
    it("toggles tree collapsed state", () => {
      expect(useWorkspaceStore.getState().treeCollapsed).toBe(false);
      useWorkspaceStore.getState().toggleTree();
      expect(useWorkspaceStore.getState().treeCollapsed).toBe(true);
      useWorkspaceStore.getState().toggleTree();
      expect(useWorkspaceStore.getState().treeCollapsed).toBe(false);
    });

    it("clamps tree width to valid range", () => {
      useWorkspaceStore.getState().setTreeWidth(50);
      expect(useWorkspaceStore.getState().treeWidth).toBe(140); // min

      useWorkspaceStore.getState().setTreeWidth(1000);
      expect(useWorkspaceStore.getState().treeWidth).toBe(480); // max
    });
  });

  describe("chat height", () => {
    it("clamps to valid range", () => {
      useWorkspaceStore.getState().setChatHeight(0.01);
      expect(useWorkspaceStore.getState().chatHeight).toBe(0.15);

      useWorkspaceStore.getState().setChatHeight(0.99);
      expect(useWorkspaceStore.getState().chatHeight).toBe(0.7);
    });
  });

  describe("section refresh", () => {
    it("increments refresh key for a section", () => {
      const initial = useWorkspaceStore.getState().sectionRefreshKey.notes;
      useWorkspaceStore.getState().triggerRefresh("notes");
      expect(useWorkspaceStore.getState().sectionRefreshKey.notes).toBe(initial + 1);
    });
  });

  describe("block system", () => {
    it("adds a block", () => {
      useWorkspaceStore.getState().addBlock("quiz");
      const blocks = useWorkspaceStore.getState().spaceLayout.blocks;
      expect(blocks).toHaveLength(1);
      expect(blocks[0].type).toBe("quiz");
      expect(blocks[0].source).toBe("user");
    });

    it("removes a block and supports undo", () => {
      useWorkspaceStore.getState().addBlock("quiz");
      const blockId = useWorkspaceStore.getState().spaceLayout.blocks[0].id;

      useWorkspaceStore.getState().removeBlock(blockId);
      expect(useWorkspaceStore.getState().spaceLayout.blocks).toHaveLength(0);
      expect(useWorkspaceStore.getState().lastRemovedBlock).not.toBeNull();

      useWorkspaceStore.getState().undoRemoveBlock();
      expect(useWorkspaceStore.getState().spaceLayout.blocks).toHaveLength(1);
    });

    it("resizes a block", () => {
      useWorkspaceStore.getState().addBlock("quiz");
      const blockId = useWorkspaceStore.getState().spaceLayout.blocks[0].id;

      useWorkspaceStore.getState().resizeBlock(blockId, "full");
      expect(useWorkspaceStore.getState().spaceLayout.blocks[0].size).toBe("full");
    });

    it("updates block config", () => {
      useWorkspaceStore.getState().addBlock("quiz");
      const blockId = useWorkspaceStore.getState().spaceLayout.blocks[0].id;

      useWorkspaceStore.getState().updateBlockConfig(blockId, { difficulty: "hard" });
      expect(useWorkspaceStore.getState().spaceLayout.blocks[0].config.difficulty).toBe("hard");
    });
  });

  describe("layout history", () => {
    it("supports undo", () => {
      useWorkspaceStore.getState().addBlock("quiz");
      expect(useWorkspaceStore.getState().spaceLayout.blocks).toHaveLength(1);

      const undone = useWorkspaceStore.getState().undoLayout();
      expect(undone).toBe(true);
      expect(useWorkspaceStore.getState().spaceLayout.blocks).toHaveLength(0);
    });

    it("returns false when no history", () => {
      const undone = useWorkspaceStore.getState().undoLayout();
      expect(undone).toBe(false);
    });
  });
});
