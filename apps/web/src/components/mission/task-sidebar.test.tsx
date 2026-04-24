import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TaskSidebar } from "./task-sidebar";
import type { RoomTask } from "@/lib/api/paths";

function task(
  id: string,
  overrides: Partial<RoomTask> = {},
): RoomTask {
  return {
    id,
    task_order: 0,
    question_type: "mc",
    question: `Q ${id}`,
    options: null,
    is_complete: false,
    difficulty_layer: null,
    ...overrides,
  };
}

describe("<TaskSidebar>", () => {
  it("renders all four distinct states in one pass", () => {
    // One task in each of: done / current / up-next / locked.
    // Task `cap` is in capstoneIds but task `b` (non-capstone, !complete)
    // is still open, so `cap` is Locked rather than Up next.
    const tasks: RoomTask[] = [
      task("a", { is_complete: true }),
      task("b", { is_complete: false }),
      task("c", { is_complete: false }),
      task("cap", { is_complete: false }),
    ];
    const onSelect = vi.fn();
    render(
      <TaskSidebar
        tasks={tasks}
        currentTaskId="b"
        capstoneIds={["cap"]}
        onSelect={onSelect}
      />,
    );

    expect(
      screen.getByTestId("task-sidebar-item-a").getAttribute("data-state"),
    ).toBe("done");
    expect(
      screen.getByTestId("task-sidebar-item-b").getAttribute("data-state"),
    ).toBe("current");
    expect(
      screen.getByTestId("task-sidebar-item-c").getAttribute("data-state"),
    ).toBe("up-next");
    expect(
      screen.getByTestId("task-sidebar-item-cap").getAttribute("data-state"),
    ).toBe("locked");

    // The visible label strings match the §10 copy contract.
    expect(screen.getByTestId("task-sidebar-item-a-state").textContent).toBe(
      "Done",
    );
    expect(screen.getByTestId("task-sidebar-item-b-state").textContent).toBe(
      "Current",
    );
    expect(screen.getByTestId("task-sidebar-item-c-state").textContent).toBe(
      "Up next",
    );
    expect(
      screen.getByTestId("task-sidebar-item-cap-state").textContent,
    ).toBe("Locked");
  });

  it("unlocks capstone once every non-capstone task is complete", () => {
    const tasks: RoomTask[] = [
      task("a", { is_complete: true }),
      task("b", { is_complete: true }),
      task("cap", { is_complete: false }),
    ];
    render(
      <TaskSidebar
        tasks={tasks}
        currentTaskId="cap"
        capstoneIds={["cap"]}
        onSelect={() => {}}
      />,
    );
    // Capstone is the current task (no longer locked) once gating passes.
    expect(
      screen.getByTestId("task-sidebar-item-cap").getAttribute("data-state"),
    ).toBe("current");
  });

  it("invokes onSelect on click for non-locked tasks", async () => {
    const tasks: RoomTask[] = [
      task("a", { is_complete: false }),
      task("b", { is_complete: false }),
    ];
    const onSelect = vi.fn();
    render(
      <TaskSidebar
        tasks={tasks}
        currentTaskId="a"
        capstoneIds={[]}
        onSelect={onSelect}
      />,
    );
    await userEvent.click(screen.getByTestId("task-sidebar-item-b"));
    expect(onSelect).toHaveBeenCalledWith("b");
  });

  it("does not invoke onSelect when the target is locked", async () => {
    const tasks: RoomTask[] = [
      task("a", { is_complete: false }),
      task("cap", { is_complete: false }),
    ];
    const onSelect = vi.fn();
    render(
      <TaskSidebar
        tasks={tasks}
        currentTaskId="a"
        capstoneIds={["cap"]}
        onSelect={onSelect}
      />,
    );
    const locked = screen.getByTestId("task-sidebar-item-cap");
    // Disabled buttons don't fire click — assert the attribute reflects state.
    expect(locked.getAttribute("aria-disabled")).toBe("true");
    expect(locked).toBeDisabled();
    await userEvent.click(locked);
    expect(onSelect).not.toHaveBeenCalled();
  });
});
