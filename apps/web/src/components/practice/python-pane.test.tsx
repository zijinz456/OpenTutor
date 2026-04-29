import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PythonPane } from "./python-pane";
import type { RoomTask } from "@/lib/api/paths";

// Stub TaskRenderer — we don't want Monaco / pyodide / API in unit
// tests. The real wiring is exercised by `practice-shell.test.tsx`
// (shell-level) and by Phase 11 / Phase 16a integration tests
// (renderer-level). Here we only check that PythonPane composes the
// two correctly. The stub exposes both onCorrect and onAttempt so
// the attempted-latch test can drive each path independently.
vi.mock("@/components/path/RoomTaskList", () => ({
  TaskRenderer: ({
    task,
    onCorrect,
    onAttempt,
  }: {
    task: { id: string };
    onCorrect: () => void;
    onAttempt?: () => void;
  }) => (
    <div data-testid={`task-renderer-stub-${task.id}`}>
      <button
        type="button"
        data-testid={`task-renderer-correct-${task.id}`}
        onClick={onCorrect}
      >
        stub-correct:{task.id}
      </button>
      <button
        type="button"
        data-testid={`task-renderer-attempt-${task.id}`}
        onClick={() => onAttempt?.()}
      >
        stub-attempt:{task.id}
      </button>
    </div>
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

    // Click the stubbed renderer's correct button to simulate a
    // correct submission.
    fireEvent.click(screen.getByTestId("task-renderer-correct-t9"));
    expect(handleCorrect).toHaveBeenCalledTimes(1);
  });

  it("hides the Next-task CTA until the renderer reports an attempt", () => {
    const handleAdvance = vi.fn();
    render(
      <PythonPane
        task={buildTask({ id: "ta" })}
        onAdvance={handleAdvance}
      />,
    );

    // Pre-attempt: CTA hidden so the user must engage with the
    // current task before being offered a way forward.
    expect(screen.queryByTestId("practice-shell-advance-ta")).toBeNull();

    // Simulate any submit roundtrip (correct or miss). Phase B fix —
    // the latch flips on every attempt so even a wrong-answer pane
    // gives the user an unmissable advance affordance.
    fireEvent.click(screen.getByTestId("task-renderer-attempt-ta"));

    const advance = screen.getByTestId("practice-shell-advance-ta");
    expect(advance).toHaveTextContent("Next task");
    fireEvent.click(advance);
    expect(handleAdvance).toHaveBeenCalledTimes(1);
  });

  it("resets the attempted latch on task switch (no stale CTA across tasks)", () => {
    // Mission page uses `<PythonPane key={currentTask.id} … />` so a
    // task swap remounts the pane and useState reinitializes. Mirror
    // that with `key=` here to assert the invariant holds end-to-end.
    const handleAdvance = vi.fn();
    const { rerender } = render(
      <PythonPane
        key="tA"
        task={buildTask({ id: "tA" })}
        onAdvance={handleAdvance}
      />,
    );

    // Attempt task A → CTA visible.
    fireEvent.click(screen.getByTestId("task-renderer-attempt-tA"));
    expect(screen.getByTestId("practice-shell-advance-tA")).toBeInTheDocument();

    // Swap to task B (parent-driven, new key forces remount). Pane
    // should re-init with attempted=false and the CTA stays hidden
    // until B is attempted.
    rerender(
      <PythonPane
        key="tB"
        task={buildTask({ id: "tB" })}
        onAdvance={handleAdvance}
      />,
    );
    expect(screen.queryByTestId("practice-shell-advance-tB")).toBeNull();
  });

  it("omits onAdvance when none is wired (last task in mission)", () => {
    render(<PythonPane task={buildTask({ id: "tend" })} />);
    fireEvent.click(screen.getByTestId("task-renderer-attempt-tend"));
    // No onAdvance prop → shell renders nothing for the CTA slot
    // even after attempt.
    expect(screen.queryByTestId("practice-shell-advance-tend")).toBeNull();
  });

  it("hides the shell submit button entirely (TaskRenderer owns submit)", () => {
    render(<PythonPane task={buildTask()} />);

    // Review follow-up: a disabled "Run tests" shell submit sitting
    // above the real run button was visually misleading. The Python
    // variant now passes `hideSubmit` to the shell so the only
    // submit affordance is the one TaskRenderer renders below.
    expect(screen.queryByTestId("practice-shell-submit-t1")).toBeNull();
  });

  it("still renders explain rail and Next-task CTA after attempt (hideSubmit only hides submit)", () => {
    // Defends against the regression where someone copies hideSubmit
    // expecting it to also collapse the bottom row — shell still
    // renders cross-variant affordances when the renderer signals an
    // attempt.
    const handleAdvance = vi.fn();
    render(
      <PythonPane
        task={buildTask({ id: "trail" })}
        onAdvance={handleAdvance}
      />,
    );

    // Explain rail mounts unconditionally (mandatory across variants).
    expect(screen.getByTestId("explain-step-textarea-trail")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("task-renderer-attempt-trail"));
    expect(screen.getByTestId("practice-shell-advance-trail")).toBeInTheDocument();
  });
});
