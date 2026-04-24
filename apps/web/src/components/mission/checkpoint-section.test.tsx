import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CheckpointSection } from "./checkpoint-section";
import type { RoomTask } from "@/lib/api/paths";

function task(id: string, overrides: Partial<RoomTask> = {}): RoomTask {
  return {
    id,
    task_order: 0,
    question_type: "mc",
    question: `Question for ${id}`,
    options: null,
    is_complete: false,
    difficulty_layer: null,
    ...overrides,
  };
}

describe("<CheckpointSection>", () => {
  it("renders one item per resolvable capstone id", () => {
    const tasks = [task("a"), task("b"), task("c"), task("d")];
    render(
      <CheckpointSection
        capstoneIds={["b", "c"]}
        tasks={tasks}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByTestId("checkpoint-section")).toBeInTheDocument();
    expect(screen.getByTestId("checkpoint-item-b")).toBeInTheDocument();
    expect(screen.getByTestId("checkpoint-item-c")).toBeInTheDocument();
    // Non-capstone tasks are NOT shown.
    expect(screen.queryByTestId("checkpoint-item-a")).toBeNull();
    expect(screen.queryByTestId("checkpoint-item-d")).toBeNull();
  });

  it("renders nothing when capstoneIds is empty", () => {
    const tasks = [task("a")];
    const { container } = render(
      <CheckpointSection
        capstoneIds={[]}
        tasks={tasks}
        onSelect={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("checkpoint-section")).toBeNull();
  });

  it("renders nothing when no capstone id resolves to a task", () => {
    const tasks = [task("a")];
    const { container } = render(
      <CheckpointSection
        capstoneIds={["does-not-exist"]}
        tasks={tasks}
        onSelect={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("calls onSelect with the capstone task id when clicked", async () => {
    const tasks = [task("a"), task("cap")];
    const onSelect = vi.fn();
    render(
      <CheckpointSection
        capstoneIds={["cap"]}
        tasks={tasks}
        onSelect={onSelect}
      />,
    );
    await userEvent.click(screen.getByTestId("checkpoint-item-cap"));
    expect(onSelect).toHaveBeenCalledWith("cap");
  });
});
