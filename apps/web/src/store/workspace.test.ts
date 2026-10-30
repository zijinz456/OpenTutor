import { describe, it, expect, beforeEach } from "vitest";
import { useWorkspaceStore } from "./workspace";

describe("useWorkspaceStore", () => {
  beforeEach(() => {
    // Reset store to initial state
    useWorkspaceStore.setState({
      selectedNodeId: null,
      practiceActiveTab: null,
      spaceLayout: { templateId: null, blocks: [], columns: 2 },
      layoutHistory: [],
      lastRemovedBlock: null,
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
