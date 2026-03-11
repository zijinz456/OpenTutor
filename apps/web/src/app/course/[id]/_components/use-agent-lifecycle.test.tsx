import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWorkspaceStore } from "@/store/workspace";
import type { SpaceLayout } from "@/lib/block-system/types";
import { useModeEvaluator } from "./use-agent-lifecycle";

const listStudyGoals = vi.fn();
const getCourseProgress = vi.fn();
const updateUnlockContext = vi.fn();

vi.mock("@/lib/api", () => ({
  listStudyGoals: (...args: unknown[]) => listStudyGoals(...args),
  getCourseProgress: (...args: unknown[]) => getCourseProgress(...args),
}));

vi.mock("@/lib/block-system/feature-unlock", () => ({
  updateUnlockContext: (...args: unknown[]) => updateUnlockContext(...args),
}));

vi.mock("@/lib/i18n-context", () => ({
  useT: () => (key: string) => key,
  useTF: () => (key: string) => key,
}));

describe("useModeEvaluator", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    sessionStorage.clear();
    localStorage.clear();
    listStudyGoals.mockReset();
    getCourseProgress.mockReset();
    updateUnlockContext.mockReset();
    useWorkspaceStore.setState({
      spaceLayout: {
        templateId: null,
        mode: "course_following",
        columns: 2,
        blocks: [],
      } as SpaceLayout,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries once after failure and writes latch only after success", async () => {
    listStudyGoals
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce([]);
    getCourseProgress.mockResolvedValue({
      average_mastery: 0.42,
      mastered: 1,
      reviewed: 1,
      in_progress: 1,
    });

    const queueModeSuggestion = vi.fn(() => true);
    renderHook(() => useModeEvaluator("course-1", { id: "course-1" }, true, queueModeSuggestion));

    await vi.waitFor(() => {
      expect(listStudyGoals).toHaveBeenCalledTimes(1);
    });

    const retryLatch = JSON.parse(sessionStorage.getItem("agent_mode_eval_course-1") || "{}");
    expect(retryLatch.successAt).toBeUndefined();
    expect(typeof retryLatch.retryAt).toBe("number");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    await vi.waitFor(() => {
      expect(listStudyGoals).toHaveBeenCalledTimes(2);
      expect(getCourseProgress).toHaveBeenCalledTimes(1);
    });

    const successLatch = JSON.parse(sessionStorage.getItem("agent_mode_eval_course-1") || "{}");
    expect(typeof successLatch.successAt).toBe("number");
    expect(typeof successLatch.fingerprint).toBe("string");
    expect(successLatch.retryAt).toBeUndefined();
  });
});
