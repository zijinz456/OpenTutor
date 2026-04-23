import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { TraceBlock } from "./trace-block";
import type { AnswerResult } from "@/lib/api";

type SubmitFn = (answer: string) => Promise<AnswerResult>;

function renderBlock(
  overrides: {
    onSubmit?: unknown;
    questionText?: string;
    correctAnswer?: string | null;
  } = {},
) {
  const onSubmit: SubmitFn =
    (overrides.onSubmit as SubmitFn | undefined) ??
    ((vi.fn().mockResolvedValue({
      is_correct: true,
      correct_answer: null,
      explanation: "Exactly right.",
    }) as unknown) as SubmitFn);

  render(
    <TraceBlock
      problemId="trace-1"
      questionText={
        overrides.questionText ??
        "What does this print?\n\n```python\nprint('hi')\n```"
      }
      correctAnswer={overrides.correctAnswer}
      onSubmit={onSubmit}
    />,
  );

  return { onSubmit };
}

describe("TraceBlock", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders prompt, textarea, and submit button", () => {
    renderBlock();

    expect(screen.getByText(/what does this print/i)).toBeInTheDocument();
    expect(screen.getByTestId("trace-block-answer")).toBeInTheDocument();
    expect(screen.getByTestId("trace-block-submit")).toBeInTheDocument();
  });

  it("submit click calls onSubmit with the exact answer text", async () => {
    const { onSubmit } = renderBlock();

    fireEvent.change(screen.getByTestId("trace-block-answer"), {
      target: { value: "line 1\nline 2\n" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("trace-block-submit"));
    });

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith("line 1\nline 2\n");
  });

  it("shows the correct verdict banner on a successful response", async () => {
    renderBlock({
      onSubmit: vi.fn().mockResolvedValue({
        is_correct: true,
        correct_answer: null,
        explanation: "Exactly right.",
      }),
    });

    fireEvent.change(screen.getByTestId("trace-block-answer"), {
      target: { value: "hi" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("trace-block-submit"));
    });

    const verdict = await screen.findByTestId("trace-block-result-correct");
    expect(verdict.textContent).toContain("Correct");
    expect(verdict.textContent).toContain("Exactly right");
  });

  it("shows an inline error message when submit fails", async () => {
    renderBlock({
      onSubmit: vi.fn().mockRejectedValue(new Error("network down")),
    });

    fireEvent.change(screen.getByTestId("trace-block-answer"), {
      target: { value: "hi" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("trace-block-submit"));
    });

    await waitFor(() =>
      expect(screen.getByTestId("trace-block-submit-error")).toHaveTextContent(
        /network down/i,
      ),
    );
  });
});
