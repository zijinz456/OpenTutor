import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@/test-utils";
import ReviewPage from "./page";

const getReviewSession = vi.fn();
const submitReviewRating = vi.fn();
const trackApiFailure = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "course-1" }),
  useRouter: () => ({
    push: vi.fn(),
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
  useTF: () => (key: string, params?: Record<string, unknown>) =>
    params ? `${key}:${JSON.stringify(params)}` : key,
}));

describe("ReviewPage recall reveal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders recall question and answer when present after Show Details", async () => {
    getReviewSession.mockResolvedValue({
      course_id: "course-1",
      count: 1,
      items: [
        {
          concept_id: "concept-1",
          concept_label: "Chain Rule",
          mastery: 0.4,
          stability_days: 1.2,
          retrievability: 0.5,
          urgency: "urgent",
          cluster: null,
          last_reviewed: null,
          recall_question: "What is d/dx[sin(x^2)]?",
          recall_answer: "2x * cos(x^2)",
        },
      ],
    });

    const { user } = render(<ReviewPage />);

    await screen.findByText("Chain Rule");
    await user.click(screen.getByRole("button", { name: "review.showDetails" }));

    expect(screen.getByText("review.recallQuestion")).toBeInTheDocument();
    expect(screen.getByText("review.recallAnswer")).toBeInTheDocument();
    expect(screen.getByText("What is d/dx[sin(x^2)]?")).toBeInTheDocument();
    expect(screen.getByText("2x * cos(x^2)")).toBeInTheDocument();
  });

  it("omits recall blocks when recall fields are absent", async () => {
    getReviewSession.mockResolvedValue({
      course_id: "course-1",
      count: 1,
      items: [
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

    const { user } = render(<ReviewPage />);

    await screen.findByText("Concept Two");
    await user.click(screen.getByRole("button", { name: "review.showDetails" }));

    expect(screen.queryByText("review.recallQuestion")).not.toBeInTheDocument();
    expect(screen.queryByText("review.recallAnswer")).not.toBeInTheDocument();
  });
});
