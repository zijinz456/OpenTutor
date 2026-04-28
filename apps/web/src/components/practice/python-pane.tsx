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

import { useState } from "react";
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
  /** Advance to the next task. When provided, the shell renders an
   *  inline "Next task" CTA after the user attempts the current task
   *  (correct or miss). Phase B mission-progression fix. */
  onAdvance?: () => void;
}

export function PythonPane({ task, correct = false, onCorrect, onAdvance }: PythonPaneProps) {
  // Attempt latch — flips true after the underlying drill renderer
  // reports any submit verdict (correct OR incorrect). Drives the
  // shell's "Next task" affordance so the user has an unmissable
  // path forward without scanning to the fixed footer. The mission
  // page passes `key={task.id}` to PythonPane so a task switch
  // remounts the pane and useState's initial `false` re-applies
  // automatically — no manual reset effect needed.
  const [attempted, setAttempted] = useState(false);
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
          // Force a fresh renderer instance on task switch so the
          // child block's local result/selected state never bleeds
          // across tasks (no-stale-state-on-task-switch invariant).
          key={task.id}
          task={task}
          onCorrect={onCorrect ?? (() => undefined)}
          onAttempt={() => setAttempted(true)}
        />
      }
      correct={correct}
      onSubmit={() => undefined}
      submitDisabled
      submitLabel="Run tests"
      onAdvance={onAdvance}
      canAdvance={attempted}
    />
  );
}

export default PythonPane;
