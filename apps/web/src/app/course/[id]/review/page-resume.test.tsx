import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@/test-utils";
import ReviewPage from "./page";

const mockPush = vi.fn();
const getReviewSession = vi.fn();
const submitReviewRating = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "course-resume" }),
  useRouter: () => ({
    push: mockPush,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

vi.mock("@/lib/api", () => ({
  getReviewSession: (...args: unknown[]) => getReviewSession(...args),
  submitReviewRating: (...args: unknown[]) => submitReviewRating(...args),
}));

vi.mock("@/lib/error-telemetry", () => ({
  trackApiFailure: vi.fn(),
}));

vi.mock("@/lib/i18n-context", () => ({
  useT: () => (key: string) => key,
  useTF: () => (key: string, params?: Record<string, unknown>) => {
    if (!params) return key;
    return `${key}:${JSON.stringify(params)}`;
  },
}));

const SESSION_DATA = {
  course_id: "course-resume",
  count: 3,
  items: [
    {
      concept_id: "c1",
      concept_label: "Already Reviewed",
      mastery: 0.3,
      stability_days: 1,
      retrievability: 0.4,
      urgency: "overdue",
      cluster: null,
      last_reviewed: null,
    },
    {
      concept_id: "c2",
      concept_label: "Next To Review",
      mastery: 0.5,
      stability_days: 2,
      retrievability: 0.6,
      urgency: "urgent",
      cluster: null,
      last_reviewed: null,
    },
    {
      concept_id: "c3",
      concept_label: "Last Item",
      mastery: 0.7,
      stability_days: 3,
      retrievability: 0.8,
      urgency: "warning",
      cluster: null,
      last_reviewed: null,
    },
  ],
};

describe("ReviewPage session resume", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Clear sessionStorage for clean tests
    sessionStorage.clear();
    getReviewSession.mockResolvedValue(SESSION_DATA);
    submitReviewRating.mockResolvedValue({
      concept_id: "c1",
      rating: "good",
      new_mastery: 0.5,
      new_stability_days: 2,
    });
  });

  it("resumes from saved progress by skipping already-rated items", async () => {
    // Pre-save one rating in sessionStorage (simulating a page refresh)
    sessionStorage.setItem(
      "review-ratings-course-resume",
      JSON.stringify([["c1", "good"]]),
    );

    render(<ReviewPage />);

    // Should skip c1 ("Already Reviewed") and show c2 ("Next To Review")
    await waitFor(() => {
      expect(screen.getByText("Next To Review")).toBeInTheDocument();
    });
    expect(screen.queryByText("Already Reviewed")).not.toBeInTheDocument();
  });

  it("persists ratings to sessionStorage after rating", async () => {
    const { user } = render(<ReviewPage />);

    await screen.findByText("Already Reviewed");
    await user.click(screen.getByRole("button", { name: "review.showDetails" }));
    await user.click(screen.getByRole("button", { name: "review.good" }));

    await waitFor(() => {
      const saved = sessionStorage.getItem("review-ratings-course-resume");
      expect(saved).toBeTruthy();
      const parsed = JSON.parse(saved!);
      expect(parsed).toEqual([["c1", "good"]]);
    });
  });

  it("clears sessionStorage when all items are reviewed", async () => {
    // Pre-save all ratings — session is complete
    sessionStorage.setItem(
      "review-ratings-course-resume",
      JSON.stringify([["c1", "good"], ["c2", "easy"], ["c3", "good"]]),
    );

    render(<ReviewPage />);

    // Should show completion screen
    await waitFor(() => {
      expect(screen.getByText("review.complete")).toBeInTheDocument();
    });

    // sessionStorage should be cleared
    expect(sessionStorage.getItem("review-ratings-course-resume")).toBeNull();
  });
});
