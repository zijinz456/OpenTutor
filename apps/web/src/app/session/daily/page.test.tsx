import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DailySessionPage from "./page";
import { useDailySessionStore } from "@/store/daily-session";
import { LocaleProvider } from "@/lib/i18n-context";
import type { DailyPlanCard } from "@/lib/api";

const mockPush = vi.fn();
const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    replace: mockReplace,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const submitAnswerMock = vi.fn();
const getDailyPlanMock = vi.fn();

vi.mock("@/lib/api", async () => {
  return {
    submitAnswer: (...args: unknown[]) => submitAnswerMock(...args),
    getDailyPlan: (...args: unknown[]) => getDailyPlanMock(...args),
  };
});

// Stub the heavy interactive blocks — daily session's MC path is what we
// exercise here. Code/lab block dispatch is covered separately in
// quiz-view.test.tsx; the guards (`readCodeMeta`/`readLabMeta`) mirror
// those already tested in-situ.
vi.mock("@/components/blocks/code-exercise-block", () => ({
  CodeExerciseBlock: () => <div data-testid="code-block-stub" />,
}));
vi.mock("@/components/blocks/lab-exercise-block", () => ({
  LabExerciseBlock: () => <div data-testid="lab-block-stub" />,
}));

function makeCard(id: string, question: string): DailyPlanCard {
  return {
    id,
    question_type: "multiple_choice",
    question,
    options: { a: "Alpha", b: "Bravo", c: "Charlie" },
    correct_answer: null,
    explanation: null,
    difficulty_layer: 1,
    content_node_id: null,
    problem_metadata: null,
  };
}

function renderWithProvider() {
  return render(
    <LocaleProvider>
      <DailySessionPage />
    </LocaleProvider>,
  );
}

describe("/session/daily page", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockPush.mockReset();
    mockReplace.mockReset();
    submitAnswerMock.mockReset();
    getDailyPlanMock.mockReset();
    useDailySessionStore.getState().reset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("redirects home when the store is empty", async () => {
    renderWithProvider();
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/");
    });
  });

  it("renders the current card question", () => {
    // Cast: production `DailySessionSize` is 1 | 5 | 10 — the store is
    // size-agnostic and 3 lets us exercise the happy path without setting
    // up a 5-card fixture.
    useDailySessionStore
      .getState()
      .start(3 as unknown as 5, [
        makeCard("c1", "First question?"),
        makeCard("c2", "Second question?"),
        makeCard("c3", "Third question?"),
      ]);
    renderWithProvider();
    expect(screen.getByTestId("daily-session-question")).toHaveTextContent(
      "First question?",
    );
  });

  it("drives through 3 cards and shows closure with correct stats", async () => {
    useDailySessionStore
      .getState()
      .start(3 as unknown as 5, [
        makeCard("c1", "Q1"),
        makeCard("c2", "Q2"),
        makeCard("c3", "Q3"),
      ]);
    submitAnswerMock
      .mockResolvedValueOnce({ is_correct: true, correct_answer: "a", explanation: "ok" })
      .mockResolvedValueOnce({ is_correct: false, correct_answer: "b", explanation: "nope" })
      .mockResolvedValueOnce({ is_correct: true, correct_answer: "c", explanation: "yes" });

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProvider();

    // Card 1 → correct
    await user.click(screen.getByTestId("quiz-option-a"));
    await waitFor(() =>
      expect(useDailySessionStore.getState().answered).toBe(1),
    );
    act(() => {
      vi.advanceTimersByTime(600);
    });
    await waitFor(() =>
      expect(screen.getByTestId("daily-session-question")).toHaveTextContent("Q2"),
    );

    // Card 2 → wrong
    await user.click(screen.getByTestId("quiz-option-a"));
    await waitFor(() =>
      expect(useDailySessionStore.getState().answered).toBe(2),
    );
    act(() => {
      vi.advanceTimersByTime(600);
    });
    await waitFor(() =>
      expect(screen.getByTestId("daily-session-question")).toHaveTextContent("Q3"),
    );

    // Card 3 → correct, triggers finish
    await user.click(screen.getByTestId("quiz-option-c"));
    await waitFor(() =>
      expect(useDailySessionStore.getState().finished).toBe(true),
    );

    // Closure screen renders with 2 correct / 3 total
    await waitFor(() =>
      expect(screen.getByTestId("session-closure")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("session-closure-stats")).toHaveTextContent(
      "3 cards reviewed · 2 remembered",
    );
  });

  it("routes home from the exit button", async () => {
    useDailySessionStore.getState().start(1, [makeCard("c1", "Q1")]);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProvider();
    await user.click(screen.getByTestId("daily-session-exit"));
    expect(mockPush).toHaveBeenCalledWith("/");
  });

  it("shows submit error without losing the flow", async () => {
    useDailySessionStore.getState().start(1, [makeCard("c1", "Q1")]);
    submitAnswerMock.mockRejectedValueOnce(new Error("network"));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWithProvider();

    await user.click(screen.getByTestId("quiz-option-a"));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /could not submit your answer/i,
      );
    });
    // Store should NOT have recorded an answer on failure.
    expect(useDailySessionStore.getState().answered).toBe(0);
  });
});
