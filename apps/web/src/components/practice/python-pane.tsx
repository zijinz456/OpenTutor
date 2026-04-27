"use client";

/**
 * `<PythonPane>` — Slice 3 Python-track wrapper.
 *
 * Wraps the existing Phase 11 code-running infrastructure rather than
 * reinstantiating Monaco. The Phase 11 cursor bugs (`code-exercise-block`
 * trailing newline drift + selection collapse on remount) were resolved
 * by NOT moving the editor between halves of the UI — so we honour that
 * here and keep `<TaskRenderer>` as the surface, hosted inside
 * `<PracticeShell>`'s slot.
 *
 * The pane delegates 100% of the run/submit lifecycle to `<TaskRenderer>`
 * + the per-block components (`code-exercise-block`, `apply-block`,
 * `lab-exercise-block`). The shell hosts the cross-variant affordances
 * (caption, explain rail, submit pattern); the pane is intentionally
 * thin so the existing 122-test surface stays unchanged.
 *
 * Acceptance per ТЗ §3 Slice 3 item #1: "Python mission → Monaco pane."
 * Live: yes — `<TaskRenderer>` already mounts Monaco for `apply` /
 * `code-exercise` / `lab-exercise` task types.
 */

import { TaskRenderer } from "@/components/path/RoomTaskList";
import type { RoomTask } from "@/lib/api/paths";
import { PracticeShell } from "./practice-shell";

export interface PythonPaneProps {
  task: RoomTask;
  /** Whether the user's last submission was correct — drives the
   *  shell's explain-rail initial state. Default `false` (no verdict
   *  yet) opens the rail expanded so the user can pre-explain. */
  correct?: boolean;
  /** Bumped by the parent when the underlying `<TaskRenderer>` reports
   *  a correct submission (mission page already wires this). */
  onCorrect?: () => void;
}

export function PythonPane({ task, correct = false, onCorrect }: PythonPaneProps) {
  // The shell's `onSubmit` is a no-op for the Python variant: the
  // per-block `<TaskRenderer>` children own their own primary CTAs
  // ("Run tests" / "Submit") and the API roundtrip. We expose a
  // disabled shell submit so the surface visually communicates the
  // common pattern across variants without fighting the block-level
  // controls. Keeping submit visible (vs. omitted) is intentional —
  // ТЗ §3 Slice 3 item #4: "Submit flow identical UX across 3."
  return (
    <PracticeShell
      problemId={task.id}
      variant="python"
      question={task.question}
      surface={
        <TaskRenderer
          task={task}
          onCorrect={onCorrect ?? (() => undefined)}
        />
      }
      correct={correct}
      onSubmit={() => undefined}
      submitDisabled
      submitLabel="Run tests"
    />
  );
}

export default PythonPane;
