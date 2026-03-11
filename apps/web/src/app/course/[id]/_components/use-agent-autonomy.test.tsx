import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWorkspaceStore } from "@/store/workspace";
import type { SpaceLayout } from "@/lib/block-system/types";
import { useReviewCheck } from "./use-agent-autonomy";

const getReviewSession = vi.fn();

vi.mock("@/lib/api", () => ({
  getReviewSession: (...args: unknown[]) => getReviewSession(...args),
}));

vi.mock("@/lib/block-system/feature-unlock", () => ({
  getUnlockContext: () => ({ sessionCount: 3 }),
  isBlockUnlocked: () => ({ unlocked: false, reason: "mocked" }),
  updateUnlockContext: vi.fn(),
}));

vi.mock("@/lib/i18n-context", () => ({
  useT: () => (key: string) => key,
  useTF: () => (key: string) => key,
}));

describe("useReviewCheck", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    getReviewSession.mockReset();
    sessionStorage.clear();
    localStorage.clear();
    useWorkspaceStore.setState({
      spaceLayout: {
        templateId: null,
        mode: "self_paced",
        columns: 2,
        blocks: [],
      } as SpaceLayout,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries once on failure and records review-needed insight on success", async () => {
    getReviewSession
      .mockRejectedValueOnce(new Error("temporary review failure"))
      .mockResolvedValueOnce({
        course_id: "course-1",
        count: 1,
        items: [
          {
            concept_id: "concept-1",
            concept_label: "Concept One",
            mastery: 0.2,
            stability_days: 0.5,
            retrievability: 0.2,
            urgency: "urgent",
            cluster: null,
            last_reviewed: null,
          },
        ],
      });

    renderHook(() => useReviewCheck("course-1", { id: "course-1" }, true));

    await vi.waitFor(() => {
      expect(getReviewSession).toHaveBeenCalledTimes(1);
    });

    const retryLatch = JSON.parse(sessionStorage.getItem("agent_review_check_course-1") || "{}");
    expect(retryLatch.successAt).toBeUndefined();
    expect(typeof retryLatch.retryAt).toBe("number");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    await vi.waitFor(() => {
      expect(getReviewSession).toHaveBeenCalledTimes(2);
    });

    const successLatch = JSON.parse(sessionStorage.getItem("agent_review_check_course-1") || "{}");
    expect(typeof successLatch.successAt).toBe("number");
    expect(typeof successLatch.fingerprint).toBe("string");
    expect(successLatch.retryAt).toBeUndefined();

    const hasReviewInsight = useWorkspaceStore.getState().spaceLayout.blocks.some(
      (block) => block.type === "agent_insight" && block.config.insightType === "review_needed",
    );
    expect(hasReviewInsight).toBe(true);
  });
});
