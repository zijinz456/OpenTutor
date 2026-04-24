/**
 * `<CheckpointSection>` — Slice 2 bottom-of-content-pane capstone
 * launcher.
 *
 * Renders a small card per capstone problem id, each clickable to
 * select that task in the practice pane. Null state: when the
 * mission has no capstones (`capstoneIds` empty or none of them
 * resolve to a task in the current list), the component renders
 * nothing — no headers, no empty copy, no placeholder. ТЗ §10 null-
 * state rule "Fact. Next action." is satisfied by the surrounding
 * page (which still shows a practice pane and progress footer); an
 * extra "no capstones yet" line would add noise.
 *
 * The mapping capstone_id → task relies on the same `tasks[]` the
 * sidebar uses — so a capstone id that doesn't correspond to any
 * rendered task (e.g. because the room lost a task during a re-seed)
 * is silently skipped.
 */

import type { RoomTask } from "@/lib/api/paths";

export interface CheckpointSectionProps {
  capstoneIds: string[];
  tasks: RoomTask[];
  /** Same handler shape as `TaskSidebar.onSelect` — so clicking a
   *  capstone here brings that task into the practice pane. */
  onSelect: (taskId: string) => void;
}

export function CheckpointSection({
  capstoneIds,
  tasks,
  onSelect,
}: CheckpointSectionProps) {
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const visible = capstoneIds
    .map((id) => byId.get(id))
    .filter((t): t is RoomTask => Boolean(t));

  if (visible.length === 0) return null;

  return (
    <section
      data-testid="checkpoint-section"
      className="rounded-xl border border-[var(--border-subtle,rgba(255,255,255,0.06))] bg-card p-4"
      aria-labelledby="checkpoint-heading"
    >
      <h2
        id="checkpoint-heading"
        className="text-[11px] uppercase tracking-[0.04em] font-medium text-[var(--text-muted)]"
      >
        Checkpoint
      </h2>
      <p className="mt-1 text-sm text-[var(--text-secondary,hsl(var(--muted-foreground)))]">
        Prove the mission held by clearing these.
      </p>
      <ul className="mt-3 space-y-2">
        {visible.map((task, idx) => (
          <li key={task.id}>
            <button
              type="button"
              data-testid={`checkpoint-item-${task.id}`}
              onClick={() => onSelect(task.id)}
              className={`w-full text-left rounded-md border px-3 py-2 text-sm min-h-[44px] transition-colors ${
                task.is_complete
                  ? "border-[var(--track-python,#34D399)]/40 bg-[var(--track-python,#34D399)]/5 text-[var(--text-secondary)]"
                  : "border-[var(--border-subtle,rgba(255,255,255,0.06))] hover:border-[var(--border-focus,#34D399)] hover:bg-[var(--surface-hover,rgba(255,255,255,0.04))]"
              }`}
            >
              <span className="text-[10px] tabular-nums text-[var(--text-muted)] mr-2">
                {String(idx + 1).padStart(2, "0")}
              </span>
              <span className="font-medium">{task.question}</span>
              {task.is_complete ? (
                <span className="ml-2 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                  Done
                </span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
