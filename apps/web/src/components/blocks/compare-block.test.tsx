import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { CompareBlock } from "./compare-block";
import type { AnswerResult } from "@/lib/api";

type SubmitFn = (answer: string) => Promise<AnswerResult>;

function renderBlock(
  overrides: {
    onSubmit?: unknown;
  } = {},
) {
  const onSubmit: SubmitFn =
    (overrides.onSubmit as SubmitFn | undefined) ??
    ((vi.fn().mockResolvedValue({
      is_correct: true,
      correct_answer: "A: asyncio scales better for high-latency I/O.",
      explanation: "Right tradeoff.",
    }) as unknown) as SubmitFn);

  render(
    <CompareBlock
      problemId="compare-1"
      questionText="You need to coordinate many slow network calls. Which approach fits better?"
      options={{
        a: "asyncio",
        b: "threads",
      }}
      onSubmit={onSubmit}
    />,
  );

  return { onSubmit };
}

describe("CompareBlock", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders prompt, two option cards, justification box, and disabled submit", () => {
    renderBlock();

    expect(screen.getByText(/many slow network calls/i)).toBeInTheDocument();
    expect(screen.getByTestId("compare-block-choice-A")).toBeInTheDocument();
    expect(screen.getByTestId("compare-block-choice-B")).toBeInTheDocument();
    expect(screen.getByTestId("compare-block-justify")).toBeInTheDocument();
    expect(
      screen.getByTestId("compare-block-submit"),
    ).toBeDisabled();
  });

  it("enables submit only after choice + justification and sends formatted answer", async () => {
    const { onSubmit } = renderBlock();
    const submit = screen.getByTestId(
      "compare-block-submit",
    ) as HTMLButtonElement;

    fireEvent.click(screen.getByTestId("compare-block-choice-A"));
    fireEvent.change(screen.getByTestId("compare-block-justify"), {
      target: { value: "asyncio handles many waiting sockets without one thread per task" },
    });

    expect(submit.disabled).toBe(false);

    await act(async () => {
      fireEvent.click(submit);
    });

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith(
      "A: asyncio handles many waiting sockets without one thread per task",
    );
  });

  it("shows the correct verdict banner on a successful response", async () => {
    renderBlock({
      onSubmit: vi.fn().mockResolvedValue({
        is_correct: true,
        correct_answer: "A: asyncio scales better for high-latency I/O.",
        explanation: "Right tradeoff.",
      }),
    });

    fireEvent.click(screen.getByTestId("compare-block-choice-A"));
    fireEvent.change(screen.getByTestId("compare-block-justify"), {
      target: { value: "asyncio fits many waiting sockets and avoids thread overhead" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("compare-block-submit"));
    });

    const verdict = await screen.findByTestId("compare-block-result-correct");
    expect(verdict.textContent).toContain("Correct");
    expect(verdict.textContent).toContain("Right tradeoff");
  });

  it("shows an inline error message when submit fails", async () => {
    renderBlock({
      onSubmit: vi.fn().mockRejectedValue(new Error("network down")),
    });

    fireEvent.click(screen.getByTestId("compare-block-choice-B"));
    fireEvent.change(screen.getByTestId("compare-block-justify"), {
      target: { value: "threads are easier to reason about in this small CPU-light tool" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("compare-block-submit"));
    });

    await waitFor(() =>
      expect(screen.getByTestId("compare-block-submit-error")).toHaveTextContent(
        /network down/i,
      ),
    );
  });
});
