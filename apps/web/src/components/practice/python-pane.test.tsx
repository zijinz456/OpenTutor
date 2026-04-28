import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PythonPane } from "./python-pane";
import type { RoomTask } from "@/lib/api/paths";

// Stub TaskRenderer — we don't want Monaco / pyodide / API in unit
// tests. The real wiring is exercised by `practice-shell.test.tsx`
// (shell-level) and by Phase 11 / Phase 16a integration tests
// (renderer-level). Here we only check that PythonPane composes the
// two correctly.
vi.mock("@/components/path/RoomTaskList", () => ({
  TaskRenderer: ({
    task,
    onCorrect,
  }: {
    task: { id: string };
    onCorrect: () => void;
  }) => (
    <button
      type="button"
      data-testid={`task-renderer-stub-${task.id}`}
      onClick={onCorrect}
    >
      stub:{task.id}
    </button>
  ),
}));

function buildTask(overrides: Partial<RoomTask> = {}): RoomTask {
  return {
    id: "t1",
    task_order: 0,
    question_type: "apply",
    question: "Write a list comprehension that doubles each item.",
    options: null,
    is_complete: false,
    difficulty_layer: null,
    ...overrides,
  };
}

describe("PythonPane", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders <PracticeShell> with the python variant + the task question", () => {
    render(<PythonPane task={buildTask()} />);

    // PracticeShell mounts with problemId = task.id.
    const shell = screen.getByTestId("practice-shell-t1");
    expect(shell).toBeInTheDocument();
    expect(shell).toHaveAttribute("data-variant", "python");

    // Caption is the python accent color label.
    expect(screen.getByTestId("practice-shell-caption-t1")).toHaveTextContent(
      "Python · Practice",
    );

    // Question text from the task is rendered inside the shell.
    expect(screen.getByTestId("practice-shell-question-t1")).toHaveTextContent(
      "Write a list comprehension that doubles each item.",
    );
  });

  it("hosts <TaskRenderer> in the surface slot", () => {
    render(<PythonPane task={buildTask({ id: "t42" })} />);

    // The stub renderer should sit inside the shell's surface slot.
    const surface = screen.getByTestId("practice-shell-surface-t42");
    expect(surface).toBeInTheDocument();
    expect(
      screen.getByTestId("task-renderer-stub-t42"),
    ).toBeInTheDocument();
  });

  it("forwards onCorrect from TaskRenderer to the parent callback", () => {
    const handleCorrect = vi.fn();
    render(
      <PythonPane task={buildTask({ id: "t9" })} onCorrect={handleCorrect} />,
    );

    // Click the stubbed renderer to simulate a correct submission.
    fireEvent.click(screen.getByTestId("task-renderer-stub-t9"));
    expect(handleCorrect).toHaveBeenCalledTimes(1);
  });

  it("keeps the shell submit button disabled (TaskRenderer owns submit)", () => {
    render(<PythonPane task={buildTask()} />);

    // ТЗ §3 Slice 3 item #4: keep submit visible but disabled, since
    // the per-block <TaskRenderer> children own their own primary CTA.
    const submit = screen.getByTestId("practice-shell-submit-t1");
    expect(submit).toBeDisabled();
    expect(submit).toHaveTextContent("Run tests");
  });
});
