/**
 * `<TaskSidebar>` — Slice 2 mission-page left rail (280px sticky top).
 *
 * Lists every task in the mission with one of four visual states —
 * ТЗ §10 copy contract:
 *
 *   Done      task.is_complete is true (wins over Current — a complete
 *             task that's also the active selection reads as Done so
 *             the user gets honest "you nailed task 1" signal instead
 *             of staring at a "Current" pill after answering correctly)
 *   Current   taskId === currentTaskId AND not complete
 *   Up next   future task, not complete, not in capstone gate
 *   Locked    task id is in `capstoneIds` AND not every prior non-capstone
 *             task is complete — matches the ТЗ wireframe's "Capstone 🔒"
 *
 * Clicks call `onSelect(task.id)`. Locked rows ignore clicks (aria-disabled).
 *
 * Why not use `<RoomTaskList>`
 * ---------------------------
 * `RoomTaskList` expands ALL tasks inline simultaneously (a Phase 16a
 * single-column reading pattern). The 3-pane page shows ONE task at a
 * time driven by sidebar selection; the interactive body lives in the
 * right pane via `<TaskRenderer>`. Keeping the two components separate
 * avoids a `RoomTaskList` refactor and keeps the old 16a tests green.
 */

import { Check, Circle, Lock } from "lucide-react";
import type { RoomTask } from "@/lib/api/paths";

export type TaskState = "done" | "current" | "up-next" | "locked";

export interface TaskSidebarProps {
  tasks: RoomTask[];
  currentTaskId: string | null;
  /** Capstone task ids — these display as `Locked` until every prior
   *  non-capstone task has `is_complete === true`. Empty list = no
   *  gating; every task is either done, current, or up-next. */
  capstoneIds?: string[];
  onSelect: (taskId: string) => void;
}

/** Compute the list of per-task states given current selection + gating. */
export function computeTaskStates(
  tasks: RoomTask[],
  currentTaskId: string | null,
  capstoneIds: string[],
): TaskState[] {
  const capstoneSet = new Set(capstoneIds);
  // A capstone unlocks once every non-capstone task is green. This matches
  // the ТЗ wireframe: tasks 1-4 ("Intro/Syntax/Filter/Nested") gate task 5
  // ("Capstone 🔒").
  const nonCapstoneTasks = tasks.filter((t) => !capstoneSet.has(t.id));
  const allPriorDone =
    nonCapstoneTasks.length > 0 &&
    nonCapstoneTasks.every((t) => t.is_complete);

  return tasks.map((task): TaskState => {
    // Done wins over Current — Phase B mission-progression UX. Юрій's
    // confusion: after answering task 1 correctly, sidebar still read
    // "Current" because precedence used selection over completion. Now
    // a complete task that's also the active selection reads "Done"
    // and the user can see progression at a glance.
    if (task.is_complete) return "done";
    if (task.id === currentTaskId) return "current";
    if (capstoneSet.has(task.id) && !allPriorDone) return "locked";
    return "up-next";
  });
}

const STATE_LABELS: Record<TaskState, string> = {
  done: "Done",
  current: "Current",
  "up-next": "Up next",
  locked: "Locked",
};

export function TaskSidebar({
  tasks,
  currentTaskId,
  capstoneIds = [],
  onSelect,
}: TaskSidebarProps) {
  const states = computeTaskStates(tasks, currentTaskId, capstoneIds);

  return (
    <aside
      data-testid="task-sidebar"
      className="w-full lg:w-[280px] lg:sticky lg:top-4 shrink-0"
      aria-label="Mission tasks"
    >
      <div className="text-[11px] uppercase tracking-[0.04em] font-medium text-[var(--text-muted)] mb-2 px-1">
        Tasks
      </div>
      <ol className="space-y-1">
        {tasks.map((task, idx) => {
          const state = states[idx];
          const label = STATE_LABELS[state];
          const isInteractive = state !== "locked";
          return (
            <li key={task.id}>
              <button
                type="button"
                data-testid={`task-sidebar-item-${task.id}`}
                data-state={state}
                aria-current={state === "current" ? "step" : undefined}
                aria-disabled={!isInteractive}
                disabled={!isInteractive}
                onClick={() => {
                  if (isInteractive) onSelect(task.id);
                }}
                className={`w-full text-left flex items-center gap-2 rounded-md px-2 py-2 text-sm transition-colors min-h-[44px] ${stateClass(
                  state,
                )}`}
              >
                <StateIcon state={state} />
                <span className="flex-1 min-w-0 truncate" title={task.question}>
                  <span className="text-[10px] tabular-nums text-[var(--text-muted)] mr-1.5">
                    {String(idx + 1).padStart(2, "0")}
                  </span>
                  {task.question}
                </span>
                <span
                  data-testid={`task-sidebar-item-${task.id}-state`}
                  className="text-[10px] uppercase tracking-wide text-[var(--text-muted)] shrink-0"
                >
                  {label}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}

function stateClass(state: TaskState): string {
  switch (state) {
    case "done":
      return "border border-transparent text-[var(--text-secondary)] hover:bg-[var(--surface-hover,rgba(255,255,255,0.04))]";
    case "current":
      return "border border-[var(--border-focus,#34D399)] bg-[var(--surface-pressed,rgba(255,255,255,0.06))] text-[var(--text-primary)]";
    case "up-next":
      return "border border-transparent text-[var(--text-secondary)] hover:bg-[var(--surface-hover,rgba(255,255,255,0.04))]";
    case "locked":
      return "border border-transparent text-[var(--text-disabled,#3F4A58)] cursor-not-allowed opacity-70";
  }
}

function StateIcon({ state }: { state: TaskState }) {
  switch (state) {
    case "done":
      return (
        <Check
          aria-hidden="true"
          className="size-4 shrink-0 text-[var(--track-python,#34D399)]"
        />
      );
    case "current":
      return (
        <span
          aria-hidden="true"
          className="size-2 shrink-0 rounded-full bg-[var(--accent-primary,#34D399)]"
        />
      );
    case "up-next":
      return (
        <Circle
          aria-hidden="true"
          className="size-4 shrink-0 text-[var(--text-muted)]"
        />
      );
    case "locked":
      return (
        <Lock
          aria-hidden="true"
          className="size-4 shrink-0 text-[var(--text-disabled,#3F4A58)]"
        />
      );
  }
}
