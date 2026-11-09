import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { listProblems, submitAnswer, type QuizProblem, type AnswerResult } from "@/lib/api";
import { useQuizPersistence } from "./use-quiz-persistence";
import { QuizView } from "./quiz-view";
import { toast } from "sonner";

vi.mock("@/lib/api", () => ({
  listProblems: vi.fn(),
  extractQuiz: vi.fn().mockResolvedValue({ problems_created: 5 }),
  submitAnswer: vi.fn(),
}));

vi.mock("@/lib/i18n-context", () => {
  const translate = (key: string) => key;
  return { useT: () => translate };
});

vi.mock("sonner", () => ({
  toast: {
    warning: vi.fn(),
  },
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

vi.mock("./use-quiz-persistence", () => {
  const persistence = { save: vi.fn(), load: vi.fn().mockReturnValue(null), clear: vi.fn() };
  return { useQuizPersistence: () => persistence };
});

describe("QuizView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listProblems).mockReset().mockResolvedValue([
      { id: "p1", question_type: "mc", question: "What color is the sky?", options: { a: "Red", b: "Blue", c: "Green" }, order_index: 0, difficulty_layer: 1, problem_metadata: { core_concept: "Atmosphere" } },
      { id: "p2", question_type: "mc", question: "2 + 2 = ?", options: { a: "3", b: "4", c: "5" }, order_index: 1, difficulty_layer: 1, problem_metadata: {} },
    ]);
    vi.mocked(submitAnswer).mockReset().mockResolvedValue({ is_correct: true, correct_answer: "b", explanation: "Blue is correct.", prerequisite_gaps: [] });
    vi.mocked(useQuizPersistence("test").load).mockReset().mockReturnValue(null);
  });

  const textProblem = (questionType: string, id = "text-1"): QuizProblem => ({
    id,
    question_type: questionType,
    question: `Answer ${id}`,
    options: null,
    order_index: 0,
  });

  it.each(["short_answer", "fill_blank"])("accepts %s only after explicit nonempty submission", async (questionType) => {
    vi.mocked(listProblems).mockResolvedValueOnce([textProblem(questionType)]);
    const user = userEvent.setup();
    render(<QuizView courseId="test" />);
    const input = await screen.findByRole("textbox", { name: "quiz.text.ariaLabel" });
    const submit = screen.getByRole("button", { name: "quiz.text.submit" });
    expect(input.tagName).toBe(questionType === "fill_blank" ? "INPUT" : "TEXTAREA");
    expect(submit).toBeDisabled();
    await user.type(input, "   ");
    expect(submit).toBeDisabled();
    await user.click(submit);
    expect(submitAnswer).not.toHaveBeenCalled();
    await user.clear(input);
    await user.type(input, "  Blue  ");
    expect(submitAnswer).not.toHaveBeenCalled();
    await user.click(submit);
    await screen.findByText(/Blue is correct/);
    expect(submitAnswer).toHaveBeenCalledExactlyOnceWith("text-1", "Blue", expect.any(Number));
    expect(input).toBeDisabled();
    expect(input).toHaveValue("Blue");
    expect(screen.queryByRole("button", { name: "quiz.text.submit" })).not.toBeInTheDocument();
  });

  it.each(["short_answer", "fill_blank"])("retains %s text after failure and allows retry", async (questionType) => {
    vi.mocked(listProblems).mockResolvedValueOnce([textProblem(questionType)]);
    vi.mocked(submitAnswer).mockRejectedValueOnce(new Error("offline"));
    const user = userEvent.setup();
    render(<QuizView courseId="test" />);
    const input = await screen.findByRole("textbox", { name: "quiz.text.ariaLabel" });
    await user.type(input, "Blue");
    await user.click(screen.getByRole("button", { name: "quiz.text.submit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("quiz.submitFailed");
    expect(input).toHaveValue("Blue");
    expect(input).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "quiz.text.submit" }));
    await screen.findByText(/Blue is correct/);
    expect(submitAnswer).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("blocks duplicate submissions and navigation while a text answer is pending", async () => {
    vi.mocked(listProblems).mockResolvedValueOnce([textProblem("short_answer"), textProblem("fill_blank", "text-2")]);
    let resolveAnswer!: (result: AnswerResult) => void;
    vi.mocked(submitAnswer).mockReturnValueOnce(new Promise((resolve) => { resolveAnswer = resolve; }));
    const user = userEvent.setup();
    render(<QuizView courseId="test" />);
    const input = await screen.findByRole("textbox", { name: "quiz.text.ariaLabel" });
    await user.type(input, "Blue");
    await user.click(screen.getByRole("button", { name: "quiz.text.submit" }));
    const submitting = screen.getByRole("button", { name: "quiz.text.submitting..." });
    expect(submitting).toBeDisabled();
    expect(input).toBeDisabled();
    expect(screen.getByRole("button", { name: "quiz.next" })).toBeDisabled();
    await user.dblClick(submitting);
    expect(submitAnswer).toHaveBeenCalledTimes(1);
    await act(async () => resolveAnswer({ is_correct: true, correct_answer: "Blue", explanation: "Saved" }));
    expect(screen.getByRole("button", { name: "quiz.next" })).toBeEnabled();
  });

  it("clears text and errors when changing questions, then restores a submitted answer", async () => {
    vi.mocked(listProblems).mockResolvedValueOnce([textProblem("short_answer"), textProblem("fill_blank", "text-2")]);
    vi.mocked(submitAnswer).mockRejectedValueOnce(new Error("offline"));
    const user = userEvent.setup();
    render(<QuizView courseId="test" />);
    await user.type(await screen.findByRole("textbox"), "draft");
    await user.click(screen.getByRole("button", { name: "quiz.text.submit" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "quiz.next" }));
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await user.type(screen.getByRole("textbox"), "Blue");
    await user.click(screen.getByRole("button", { name: "quiz.text.submit" }));
    await screen.findByText(/Blue is correct/);
    await user.click(screen.getByRole("button", { name: "quiz.prev" }));
    await user.click(screen.getByRole("button", { name: "quiz.next" }));
    expect(screen.getByRole("textbox")).toHaveValue("Blue");
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "quiz.text.submit" })).not.toBeInTheDocument();
  });

  it("restores a saved text answer on the first question without resubmitting", async () => {
    vi.mocked(listProblems).mockResolvedValueOnce([textProblem("fill_blank")]);
    vi.mocked(useQuizPersistence("test").load).mockReturnValueOnce({
      currentIdx: 0, score: { correct: 1, total: 1 }, answeredMap: { "text-1": "Blue" }, consecutiveWrong: 0, savedAt: Date.now(),
    });
    render(<QuizView courseId="test" />);
    const input = await screen.findByRole("textbox", { name: "quiz.text.ariaLabel" });
    expect(input).toHaveValue("Blue");
    expect(input).toBeDisabled();
    expect(submitAnswer).not.toHaveBeenCalled();
  });

  it("preserves explicit code submission", async () => {
    vi.mocked(listProblems).mockResolvedValueOnce([textProblem("coding")]);
    const user = userEvent.setup();
    render(<QuizView courseId="test" />);
    await user.type(await screen.findByRole("textbox", { name: "quiz.coding.ariaLabel" }), "print(42)");
    expect(submitAnswer).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "quiz.coding.submit" }));
    expect(submitAnswer).toHaveBeenCalledExactlyOnceWith("text-1", "print(42)", expect.any(Number));
  });

  it("preserves immediate true/false choice submission", async () => {
    vi.mocked(listProblems).mockResolvedValueOnce([{ ...textProblem("true_false"), options: { true: "True", false: "False" } }]);
    const user = userEvent.setup();
    render(<QuizView courseId="test" />);
    await user.click(await screen.findByRole("radio", { name: /True/ }));
    expect(submitAnswer).toHaveBeenCalledExactlyOnceWith("text-1", "true", expect.any(Number));
  });

  const multiProblem: QuizProblem = {
    id: "multi-1", question_type: "select_all", question: "Select primary colors",
    options: { a: "Red", b: "Blue", c: "Green", d: "Orange" }, order_index: 0,
  };

  it("toggles multiple answers without submitting, then submits once in option order", async () => {
    vi.mocked(listProblems).mockResolvedValueOnce([multiProblem, textProblem("fill_blank")]);
    let resolveAnswer!: (result: AnswerResult) => void;
    vi.mocked(submitAnswer).mockReturnValueOnce(new Promise((resolve) => { resolveAnswer = resolve; }));
    const user = userEvent.setup();
    render(<QuizView courseId="test" />);
    const blue = await screen.findByRole("checkbox", { name: /Blue/ });
    const red = screen.getByRole("checkbox", { name: /Red/ });
    const submit = screen.getByRole("button", { name: "quiz.text.submit" });
    expect(submit).toBeDisabled();
    await user.click(blue);
    await user.click(red);
    await user.click(red);
    expect(red).not.toBeChecked();
    expect(blue).toBeChecked();
    await user.click(red);
    expect(submitAnswer).not.toHaveBeenCalled();
    await user.click(submit);
    expect(submitAnswer).toHaveBeenCalledExactlyOnceWith("multi-1", "a,b", expect.any(Number));
    expect(red).toBeDisabled();
    expect(screen.getByRole("button", { name: "quiz.next" })).toBeDisabled();
    await user.dblClick(screen.getByRole("button", { name: "quiz.text.submitting..." }));
    expect(submitAnswer).toHaveBeenCalledTimes(1);
    await act(async () => resolveAnswer({ is_correct: true, correct_answer: "B,A", explanation: "Saved" }));
    expect(red).toHaveClass("border-green-500");
    expect(blue).toHaveClass("border-green-500");
    await user.click(screen.getByRole("button", { name: "quiz.next" }));
    await user.click(screen.getByRole("button", { name: "quiz.prev" }));
    expect(screen.getByRole("checkbox", { name: /Red/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Red/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "quiz.text.submit" })).not.toBeInTheDocument();
  });

  it("keeps multi-select choices on failure and allows an explicit retry", async () => {
    vi.mocked(listProblems).mockResolvedValueOnce([multiProblem]);
    vi.mocked(submitAnswer).mockRejectedValueOnce(new Error("offline"));
    const user = userEvent.setup();
    render(<QuizView courseId="test" />);
    await user.click(await screen.findByRole("checkbox", { name: /Red/ }));
    await user.click(screen.getByRole("checkbox", { name: /Blue/ }));
    await user.click(screen.getByRole("button", { name: "quiz.text.submit" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("checkbox", { name: /Red/ })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "quiz.text.submit" }));
    await screen.findByText(/Blue is correct/);
    expect(submitAnswer).toHaveBeenNthCalledWith(2, "multi-1", "a,b", expect.any(Number));
  });

  it("restores a saved multi-select answer on the first question", async () => {
    vi.mocked(listProblems).mockResolvedValueOnce([multiProblem]);
    vi.mocked(useQuizPersistence("test").load).mockReturnValueOnce({
      currentIdx: 0, score: { correct: 1, total: 1 }, answeredMap: { "multi-1": "B,A" }, consecutiveWrong: 0, savedAt: Date.now(),
    });
    render(<QuizView courseId="test" />);
    expect(await screen.findByRole("checkbox", { name: /Blue/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Red/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Red/ })).toBeDisabled();
    expect(submitAnswer).not.toHaveBeenCalled();
  });

  it("clears unsubmitted multi-select choices when changing questions", async () => {
    vi.mocked(listProblems).mockResolvedValueOnce([multiProblem, { ...multiProblem, id: "multi-2" }]);
    const user = userEvent.setup();
    render(<QuizView courseId="test" />);
    await user.click(await screen.findByRole("checkbox", { name: /Red/ }));
    await user.click(screen.getByRole("button", { name: "quiz.next" }));
    expect(screen.getByRole("checkbox", { name: /Red/ })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "quiz.text.submit" })).toBeDisabled();
    expect(submitAnswer).not.toHaveBeenCalled();
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
    expect(screen.getByRole("form", { name: "quiz.ariaLabel" })).toBeInTheDocument();
  });

  it("has role=radiogroup for answer options", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));
    expect(screen.getByRole("radiogroup", { name: "quiz.answerOptions" })).toBeInTheDocument();
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

  it("shows fallback feedback when explanation details are missing", async () => {
    const { submitAnswer } = await import("@/lib/api");
    vi.mocked(submitAnswer).mockResolvedValueOnce({
      is_correct: false,
      correct_answer: null,
      explanation: null,
      prerequisite_gaps: [],
    });

    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));

    fireEvent.click(screen.getByTestId("quiz-option-b"));

    await waitFor(() => {
      expect(screen.getByText("quiz.answerRecorded")).toBeInTheDocument();
      expect(screen.getByText("quiz.feedbackUnavailable")).toBeInTheDocument();
    });
    expect(toast.warning).toHaveBeenCalledWith("quiz.feedbackWarning");
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

  it("shows error state with retry when loading fails", async () => {
    const { listProblems } = await import("@/lib/api");
    vi.mocked(listProblems).mockRejectedValueOnce(new Error("network down"));

    render(<QuizView courseId="test" />);
    await waitFor(() => {
      expect(screen.getByTestId("quiz-load-error")).toBeInTheDocument();
    });
    // The failure must NOT masquerade as the "no quiz yet" empty state
    expect(screen.queryByText("quiz.empty")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("network down")).toBeInTheDocument();

    // Retry refetches (the default mock resolves) and renders the quiz
    fireEvent.click(screen.getByText("quiz.retry"));
    await waitFor(() => {
      expect(screen.getByText("What color is the sky?")).toBeInTheDocument();
    });
  });
});
