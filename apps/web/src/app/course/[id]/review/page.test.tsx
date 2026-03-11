import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@/test-utils";
import ReviewPage from "./page";

const mockPush = vi.fn();
const getReviewSession = vi.fn();
const submitReviewRating = vi.fn();
const trackApiFailure = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "course-1" }),
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
  trackApiFailure: (...args: unknown[]) => trackApiFailure(...args),
}));

vi.mock("@/lib/i18n-context", () => ({
  useT: () => (key: string) => key,
  useTF: () => (key: string, params?: Record<string, unknown>) => {
    if (!params) return key;
    return `${key}:${JSON.stringify(params)}`;
  },
}));

describe("ReviewPage rating flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getReviewSession.mockResolvedValue({
      course_id: "course-1",
      count: 2,
      items: [
        {
          concept_id: "concept-1",
          concept_label: "Concept One",
          mastery: 0.4,
          stability_days: 1.2,
          retrievability: 0.5,
          urgency: "urgent",
          cluster: null,
          last_reviewed: null,
        },
        {
          concept_id: "concept-2",
          concept_label: "Concept Two",
          mastery: 0.7,
          stability_days: 2.5,
          retrievability: 0.8,
          urgency: "warning",
          cluster: "cluster-a",
          last_reviewed: null,
        },
      ],
    });
  });

  it("keeps current card on rating failure and advances only after successful retry", async () => {
    submitReviewRating
      .mockRejectedValueOnce(new Error("rate failed"))
      .mockResolvedValueOnce({
        concept_id: "concept-1",
        rating: "good",
        new_mastery: 0.5,
        new_stability_days: 2,
      });

    const { user } = render(<ReviewPage />);

    await screen.findByText("Concept One");
    await user.click(screen.getByRole("button", { name: "review.showDetails" }));
    await user.click(screen.getByRole("button", { name: "review.good" }));

    await screen.findByText("rate failed");
    expect(screen.getByText("Concept One")).toBeInTheDocument();
    expect(screen.queryByText("Concept Two")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "review.good" }));

    await waitFor(() => {
      expect(screen.getByText("Concept Two")).toBeInTheDocument();
    });

    expect(submitReviewRating).toHaveBeenCalledTimes(2);
    expect(submitReviewRating).toHaveBeenNthCalledWith(1, "course-1", "concept-1", "good");
    expect(submitReviewRating).toHaveBeenNthCalledWith(2, "course-1", "concept-1", "good");
    expect(trackApiFailure).toHaveBeenCalledTimes(1);
  });
});
