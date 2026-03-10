import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QuizView } from "./quiz-view";

vi.mock("@/lib/api", async () => {
  const problems = [
    {
      id: "p1",
      question: "What color is the sky?",
      options: { a: "Red", b: "Blue", c: "Green" },
      difficulty_layer: 1,
      problem_metadata: { core_concept: "Atmosphere" },
    },
    {
      id: "p2",
      question: "2 + 2 = ?",
      options: { a: "3", b: "4", c: "5" },
      difficulty_layer: 1,
      problem_metadata: {},
    },
  ];
  return {
    listProblems: vi.fn().mockResolvedValue(problems),
    extractQuiz: vi.fn().mockResolvedValue({ problems_created: 5 }),
    submitAnswer: vi.fn().mockResolvedValue({
      is_correct: true,
      correct_answer: "b",
      explanation: "Blue is correct.",
      prerequisite_gaps: [],
    }),
  };
});

vi.mock("@/lib/i18n-context", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("@/store/workspace", () => ({
  useWorkspaceStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector({ sectionRefreshKey: { practice: 0 }, spaceLayout: { mode: "self_paced", blocks: [] } }),
    {
      getState: () => ({
        sectionRefreshKey: { practice: 0 },
        spaceLayout: { mode: "self_paced", blocks: [] },
        addBlock: vi.fn(),
        reorderBlocks: vi.fn(),
      }),
    },
  ),
}));

vi.mock("@/lib/block-system/feature-unlock", () => ({
  updateUnlockContext: vi.fn(),
  getUnlockContext: () => ({ practiceAttempts: 0, hasWrongAnswer: false }),
}));

vi.mock("@/components/shared/ai-feature-blocked", () => ({
  AiFeatureBlocked: () => <div data-testid="ai-blocked" />,
}));

describe("QuizView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state initially", async () => {
    render(<QuizView courseId="test" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });
  });

  it("renders quiz question after loading", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => {
      expect(screen.getByText("What color is the sky?")).toBeInTheDocument();
    });
  });

  it("has role=form with aria-label", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));
    expect(screen.getByRole("form", { name: "Quiz question" })).toBeInTheDocument();
  });

  it("has role=radiogroup for answer options", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));
    expect(screen.getByRole("radiogroup", { name: "Answer options" })).toBeInTheDocument();
  });

  it("renders answer options as radio buttons", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(3);
  });

  it("selects option and submits answer on click", async () => {
    const { submitAnswer } = await import("@/lib/api");
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));

    const optionB = screen.getByTestId("quiz-option-b");
    fireEvent.click(optionB);

    await waitFor(() => {
      expect(submitAnswer).toHaveBeenCalledWith("p1", "b", expect.any(Number));
    });
  });

  it("shows explanation after answering", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));

    fireEvent.click(screen.getByTestId("quiz-option-b"));

    await waitFor(() => {
      expect(screen.getByText(/Blue is correct/)).toBeInTheDocument();
    });
  });

  it("navigates to next question", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));

    const nextBtn = screen.getByText("quiz.next");
    fireEvent.click(nextBtn);

    await waitFor(() => {
      expect(screen.getByText("2 + 2 = ?")).toBeInTheDocument();
    });
  });

  it("disables previous button on first question", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));
    expect(screen.getByText("quiz.prev")).toBeDisabled();
  });

  it("shows core concept badge", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));
    expect(screen.getByText("Atmosphere")).toBeInTheDocument();
  });
});
