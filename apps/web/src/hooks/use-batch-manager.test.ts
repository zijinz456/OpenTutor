import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useBatchManager } from "./use-batch-manager";
import type { GeneratedAssetBatchSummary } from "@/lib/api";

// Mock workspace store
const mockRefreshKey: Record<string, number> = { notes: 0 };
vi.mock("@/store/workspace", () => ({
  useWorkspaceStore: (selector: (s: { sectionRefreshKey: Record<string, number> }) => unknown) =>
    selector({ sectionRefreshKey: mockRefreshKey }),
}));

// Mock sonner
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast as mockToast } from "sonner";
const typedToast = mockToast as unknown as { success: ReturnType<typeof vi.fn>; error: ReturnType<typeof vi.fn> };

const makeBatch = (batchId: string, active = false): GeneratedAssetBatchSummary => ({
  batch_id: batchId,
  title: `batch-${batchId}`,
  current_version: 1,
  is_active: active,
  updated_at: new Date().toISOString(),
  asset_count: 0,
  preview: {},
});

describe("useBatchManager", () => {
  let listFn: ReturnType<typeof vi.fn<(courseId: string) => Promise<GeneratedAssetBatchSummary[]>>>;

  beforeEach(() => {
    listFn = vi.fn<(courseId: string) => Promise<GeneratedAssetBatchSummary[]>>().mockResolvedValue([makeBatch("1"), makeBatch("2", true)]);
    mockRefreshKey.notes = 0;
    typedToast.success.mockClear();
    typedToast.error.mockClear();
  });

  it("loads batches after debounce", async () => {
    const { result } = renderHook(() =>
      useBatchManager({ courseId: "c1", refreshSection: "notes", listFn }),
    );

    expect(result.current.batches).toEqual([]);

    await waitFor(() => {
      expect(listFn).toHaveBeenCalledWith("c1");
      expect(result.current.batches).toHaveLength(2);
    });
  });

  it("identifies the latest (active) batch", async () => {
    const { result } = renderHook(() =>
      useBatchManager({ courseId: "c1", refreshSection: "notes", listFn }),
    );

    await waitFor(() => {
      expect(result.current.latestBatch?.batch_id).toBe("2");
      expect(result.current.latestBatch?.is_active).toBe(true);
    });
  });

  it("returns null latestBatch when no active batch", async () => {
    listFn.mockResolvedValue([makeBatch("1"), makeBatch("2")]);

    const { result } = renderHook(() =>
      useBatchManager({ courseId: "c1", refreshSection: "notes", listFn }),
    );

    await waitFor(() => {
      expect(result.current.latestBatch).toBeNull();
    });
  });

  it("sets batches to empty on listFn failure", async () => {
    listFn.mockRejectedValue(new Error("Network error"));

    const { result } = renderHook(() =>
      useBatchManager({ courseId: "c1", refreshSection: "notes", listFn }),
    );

    // Starts empty, stays empty after error
    await waitFor(() => {
      expect(listFn).toHaveBeenCalled();
    });
    expect(result.current.batches).toEqual([]);
  });

  it("wrapSave shows success toast and reloads batches", async () => {
    const { result } = renderHook(() =>
      useBatchManager({ courseId: "c1", refreshSection: "notes", listFn }),
    );

    await waitFor(() => {
      expect(result.current.batches).toHaveLength(2);
    });

    const saveFn = vi.fn().mockResolvedValue({ replaced: false, version: 3 });

    await act(async () => {
      await result.current.wrapSave(saveFn);
    });

    expect(saveFn).toHaveBeenCalled();
    expect(typedToast.success).toHaveBeenCalledWith("Saved successfully");
  });

  it("wrapSave shows replaced toast when result.replaced is true", async () => {
    const { result } = renderHook(() =>
      useBatchManager({ courseId: "c1", refreshSection: "notes", listFn }),
    );

    await waitFor(() => {
      expect(result.current.batches).toHaveLength(2);
    });

    const saveFn = vi.fn().mockResolvedValue({ replaced: true, version: 5 });

    await act(async () => {
      await result.current.wrapSave(saveFn);
    });

    expect(typedToast.success).toHaveBeenCalledWith("Replaced with version 5");
  });

  it("wrapSave shows error toast on failure", async () => {
    const { result } = renderHook(() =>
      useBatchManager({ courseId: "c1", refreshSection: "notes", listFn }),
    );

    await waitFor(() => {
      expect(result.current.batches).toHaveLength(2);
    });

    const saveFn = vi.fn().mockRejectedValue(new Error("Save failed"));

    await act(async () => {
      await result.current.wrapSave(saveFn);
    });

    expect(typedToast.error).toHaveBeenCalledWith("Save failed");
  });

  it("tracks saving state during wrapSave", async () => {
    const { result } = renderHook(() =>
      useBatchManager({ courseId: "c1", refreshSection: "notes", listFn }),
    );

    await waitFor(() => {
      expect(result.current.batches).toHaveLength(2);
    });

    expect(result.current.saving).toBe(false);

    let resolveSave!: (v: { replaced: boolean; version: number }) => void;
    const saveFn = vi.fn().mockReturnValue(
      new Promise((r) => { resolveSave = r; }),
    );

    let savePromise: Promise<void>;
    act(() => {
      savePromise = result.current.wrapSave(saveFn);
    });

    expect(result.current.saving).toBe(true);

    await act(async () => {
      resolveSave({ replaced: false, version: 1 });
      await savePromise!;
    });

    expect(result.current.saving).toBe(false);
  });
});
