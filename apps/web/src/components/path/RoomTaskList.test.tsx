import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RoomTaskList } from "./RoomTaskList";
import type { RoomTask } from "@/lib/api";

// Stub submitAnswer — each test case configures it per-run.
const submitAnswerMock = vi.fn();
vi.mock("@/lib/api", async () => ({
  submitAnswer: (...args: unknown[]) => submitAnswerMock(...args),
}));

// Replace the heavy block renderers with thin identifiable stubs so we
// can assert dispatch without pulling Monaco / markdown renderers into
// the test bundle.
vi.mock("@/components/blocks/trace-block", () => ({
  TraceBlock: ({ problemId }: { problemId: string }) => (
    <div data-testid={`trace-block-stub-${problemId}`}>trace-stub</div>
  ),
}));
vi.mock("@/components/blocks/apply-block", () => ({
  ApplyBlock: ({ problemId }: { problemId: string }) => (
    <div data-testid={`apply-block-stub-${problemId}`}>apply-stub</div>
  ),
}));
vi.mock("@/components/blocks/compare-block", () => ({
  CompareBlock: ({ problemId }: { problemId: string }) => (
    <div data-testid={`compare-block-stub-${problemId}`}>compare-stub</div>
  ),
}));
vi.mock("@/components/blocks/rebuild-block", () => ({
  RebuildBlock: ({ problemId }: { problemId: string }) => (
    <div data-testid={`rebuild-block-stub-${problemId}`}>rebuild-stub</div>
  ),
}));
vi.mock("@/components/blocks/code-exercise-block", () => ({
  CodeExerciseBlock: ({ problemId }: { problemId: string }) => (
    <div data-testid={`code-block-stub-${problemId}`}>code-stub</div>
  ),
}));
vi.mock("@/components/blocks/lab-exercise-block", () => ({
  LabExerciseBlock: ({ problemId }: { problemId: string }) => (
    <div data-testid={`lab-block-stub-${problemId}`}>lab-stub</div>
  ),
}));

function makeTask(overrides: Partial<RoomTask> = {}): RoomTask {
  return {
    id: "task-1",
    task_order: 1,
    question_type: "mc",
    question: "Which type stores decimals?",
    options: { a: "int", b: "float", c: "str" },
    is_complete: false,
    difficulty_layer: 1,
    ...overrides,
  };
}

describe("<RoomTaskList>", () => {
  beforeEach(() => {
    submitAnswerMock.mockReset();
  });

  it("dispatches `trace` question_type to the TraceBlock renderer", () => {
    render(
      <RoomTaskList
        tasks={[
          makeTask({
            id: "trace-task",
            question_type: "trace",
            options: null,
          }),
        ]}
      />,
    );
    // Uncompleted tasks auto-expand so the renderer mounts immediately.
    expect(screen.getByTestId("trace-block-stub-trace-task")).toBeInTheDocument();
  });

  it("dispatches `mc` question_type to the inline MC renderer", () => {
    render(<RoomTaskList tasks={[makeTask({ id: "mc-task" })]} />);
    expect(screen.getByTestId("mc-renderer-mc-task")).toBeInTheDocument();
    // Alphabetically-sorted options render as labelled buttons.
    expect(screen.getByTestId("mc-option-mc-task-a")).toHaveTextContent("int");
    expect(screen.getByTestId("mc-option-mc-task-b")).toHaveTextContent(
      "float",
    );
  });

  it("flips is_complete optimistically after a correct MC submission", async () => {
    const user = userEvent.setup();
    submitAnswerMock.mockResolvedValue({
      is_correct: true,
      correct_answer: "b",
      explanation: null,
    });
    const onTaskComplete = vi.fn();
    render(
      <RoomTaskList
        tasks={[makeTask({ id: "opt-task" })]}
        onTaskComplete={onTaskComplete}
      />,
    );

    await user.click(screen.getByTestId("mc-option-opt-task-b"));

    await waitFor(() => {
      expect(
        screen.getByTestId("task-card-done-opt-task"),
      ).toBeInTheDocument();
    });
    expect(submitAnswerMock).toHaveBeenCalledWith("opt-task", "b");
    expect(onTaskComplete).toHaveBeenCalledWith("opt-task");
    expect(screen.getByTestId("task-card-opt-task")).toHaveAttribute(
      "data-complete",
      "true",
    );
  });

  it("shows the Room done banner once every task is complete", () => {
    render(
      <RoomTaskList
        tasks={[
          makeTask({ id: "t1", is_complete: true }),
          makeTask({ id: "t2", is_complete: true }),
        ]}
      />,
    );
    expect(screen.getByTestId("room-task-list-banner")).toHaveTextContent(
      /done/i,
    );
  });
});
