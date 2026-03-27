import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWorkspaceStore } from "@/store/workspace";
import type { SpaceLayout, BlockInstance } from "@/lib/block-system/types";
import { useBlockPersistence } from "./use-block-persistence";

const mockUpdateCourseLayout = vi.fn();

vi.mock("@/lib/api", () => ({
  updateCourseLayout: (...args: unknown[]) => mockUpdateCourseLayout(...args),
}));

function makeLayout(blocks: BlockInstance[]): SpaceLayout {
  return {
    templateId: null,
    mode: "self_paced",
    columns: 2,
    blocks,
  };
}

describe("useBlockPersistence", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    mockUpdateCourseLayout.mockReset();
    mockUpdateCourseLayout.mockResolvedValue({ status: "ok", layout: {} });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("persists empty layouts after all blocks are removed", async () => {
    useWorkspaceStore.setState({
      spaceLayout: makeLayout([
        {
          id: "blk-1",
          type: "quiz",
          position: 0,
          size: "medium",
          config: {},
          visible: true,
          source: "user",
        },
      ]),
    });

    renderHook(() => useBlockPersistence("course-1", { metadata: {} }));
    await act(async () => {});

    act(() => {
      useWorkspaceStore.setState({ spaceLayout: makeLayout([]) });
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(mockUpdateCourseLayout).toHaveBeenCalledWith(
      "course-1",
      expect.objectContaining({ blocks: [] }),
    );

    const saved = JSON.parse(localStorage.getItem("opentutor_blocks_course-1") || "{}");
    expect(saved.blocks).toEqual([]);
  });

  it("flushes immediately on pagehide", async () => {
    useWorkspaceStore.setState({ spaceLayout: makeLayout([]) });
    renderHook(() => useBlockPersistence("course-2", { metadata: {} }));
    await act(async () => {});

    mockUpdateCourseLayout.mockClear();
    act(() => {
      window.dispatchEvent(new Event("pagehide"));
    });

    expect(mockUpdateCourseLayout).toHaveBeenCalledTimes(1);
    expect(mockUpdateCourseLayout).toHaveBeenCalledWith(
      "course-2",
      expect.objectContaining({ blocks: [] }),
    );
  });

  it("flushes on unmount (route leave)", async () => {
    useWorkspaceStore.setState({ spaceLayout: makeLayout([]) });
    const { unmount } = renderHook(() => useBlockPersistence("course-3", { metadata: {} }));
    await act(async () => {});

    mockUpdateCourseLayout.mockClear();
    unmount();

    expect(mockUpdateCourseLayout).toHaveBeenCalledTimes(1);
    expect(mockUpdateCourseLayout).toHaveBeenCalledWith(
      "course-3",
      expect.objectContaining({ blocks: [] }),
    );
  });

  it("ignores malformed local storage and falls back to server metadata", async () => {
    localStorage.setItem("opentutor_blocks_course-4", "{\"broken\":true}");
    useWorkspaceStore.setState({ spaceLayout: makeLayout([]) });

    renderHook(() =>
      useBlockPersistence("course-4", {
        metadata: {
          spaceLayout: makeLayout([
            {
              id: "server-notes",
              type: "notes",
              position: 0,
              size: "large",
              config: {},
              visible: true,
              source: "template",
            },
          ]),
        },
      }),
    );

    await act(async () => {});

    expect(useWorkspaceStore.getState().spaceLayout.blocks).toEqual([
      expect.objectContaining({
        id: "server-notes",
        type: "notes",
      }),
    ]);
  });
});
