"use client";

/**
 * `<PracticeShell>` — Slice 3 common practice surface (ТЗ §3 Slice 3).
 *
 * Same skeleton (`code/answer → run → output → explain → submit`) for
 * three variants — Python (Phase 11 code runner), English (Phase 8
 * Whisper + Phase 5 Interviewer SSE), Hacking (Phase 12 Juice Shop
 * iframe). The shell owns the layout, the submit lifecycle, and the
 * mandatory explain-in-your-own-words step that every variant ships.
 *
 * Slot model
 * ----------
 * The host passes one of the three pane wrappers (`<PythonPane>`,
 * `<EnglishPane>`, `<HackingPane>`) as the `surface` slot. The pane
 * owns its variant-specific UI (Monaco editor, textarea+voice, iframe).
 * The shell composes the pane with:
 *
 *   - a `caption` row + question text on top,
 *   - the pane's interactive surface,
 *   - an optional `output` block (per-variant — runner output, voice
 *     transcript, proof verdict),
 *   - the shared `<ExplainStep>` rail (always rendered; Phase A
 *     guardrail for the Feynman habit),
 *   - the standard primary "Submit" CTA.
 *
 * Why a thin shell instead of a deep dispatch
 * -------------------------------------------
 * The `<TaskRenderer>` we already ship in `RoomTaskList.tsx` switches
 * on `task.question_type` and inlines per-block components. That
 * works for Phase 16a's homogeneous mission UI. Slice 3's surface
 * unification is a different abstraction — it's about the *track*, not
 * the *question type*. A Python mission can contain `apply` + `trace`
 * blocks; both flow through the python variant. So `PracticeShell` is
 * the track-level wrapper that hosts those blocks plus the cross-track
 * affordances (explain, miss banner). The two abstractions compose.
 *
 * Phase A scope
 * -------------
 * The Python variant is wired live (the `surface` host plugs in the
 * existing `<TaskRenderer>` for now). English + Hacking ship as
 * pattern-ready wrappers — see the per-pane docstrings for the TODO
 * placeholders. ТЗ §3 Slice 3 acceptance items 1-5 grade the *shape*
 * of the surface, not full live wiring of every track in Phase A.
 */

import { type ReactNode } from "react";
import { ExplainStep } from "@/components/practice/explain-step";
import { Button } from "@/components/ui/button";

export type PracticeVariant = "python" | "english" | "hacking";

const VARIANT_LABEL: Record<PracticeVariant, string> = {
  python: "Python",
  english: "English",
  hacking: "Hacking",
};

const VARIANT_ACCENT: Record<PracticeVariant, string> = {
  // Track accent CSS vars from ТЗ §8. Each pane gets a single hairline
  // of color via the caption — enough to anchor the variant without
  // rainbow-ing the whole pane. Per "Top 3 visual risks → Rainbow
  // tracks" (§8): only one track at full saturation per viewport.
  python: "text-[var(--track-python,#34D399)]",
  english: "text-[var(--track-english,#60A5FA)]",
  hacking: "text-[var(--track-hacking,#F59E0B)]",
};

export interface PracticeShellProps {
  /** Stable id for the underlying problem/task — used as the storage
   *  key for `<ExplainStep>` so reflections persist per-task. */
  problemId: string;
  /** Track variant — drives caption + accent. Submit shape is identical
   *  across variants (the host's `onSubmit` deals with the variant-
   *  specific payload). */
  variant: PracticeVariant;
  /** The visible task prompt shown above the surface. */
  question: string;
  /** Variant-specific interactive UI — Monaco for python, textarea+voice
   *  for english, iframe+proof for hacking. */
  surface: ReactNode;
  /** Optional output / verdict block — runner stdout, voice transcript,
   *  proof check result. Slot is rendered between the surface and the
   *  explain rail; pass `null` when nothing has run yet. */
  output?: ReactNode;
  /** Whether the user's last submission was correct. Drives the
   *  initial collapsed/expanded state of the explain rail (miss →
   *  expanded + auto-focused, correct → collapsed pill). */
  correct: boolean;
  /** Submit handler. Returns whatever shape the host needs — the
   *  shell only kicks the lifecycle. The shell does NOT own the
   *  network call; per-variant panes already have their submit logic
   *  (Pyodide for python, fetch+SSE for english, etc.). */
  onSubmit: () => void | Promise<void>;
  /** Disable the submit button (e.g., empty answer, network in flight).
   *  Defaults to `false`. */
  submitDisabled?: boolean;
  /** Submit-button copy. Defaults to "Submit checkpoint & advance"
   *  per ТЗ §10 line 901; pass "Run tests" or another verb when the
   *  variant uses a different primary action. */
  submitLabel?: string;
  /** Hide the shell-level submit button entirely. Used by panes whose
   *  inner surface owns the primary CTA — e.g. `<PythonPane>` where
   *  `<TaskRenderer>` ships its own "Run tests" / "Submit" button. The
   *  shell still renders the explain rail and the optional Next-task
   *  CTA so cross-variant affordances stay consistent. */
  hideSubmit?: boolean;
  /** Advance to the next task in the mission. When provided alongside
   *  `canAdvance`, the shell renders a secondary "Next task" CTA next
   *  to Submit so the user never has to scan to the fixed footer after
   *  a verdict lands. Phase B mission-progression UX (Юрій stuck
   *  staring at the explained MC pane). */
  onAdvance?: () => void;
  /** Whether the next-task CTA should be visible+enabled. Hosts flip
   *  this to `true` after the first submit attempt (correct OR miss)
   *  so the user has an unmissable way forward. */
  canAdvance?: boolean;
}

export function PracticeShell({
  problemId,
  variant,
  question,
  surface,
  output,
  correct,
  onSubmit,
  submitDisabled = false,
  submitLabel = "Submit checkpoint & advance",
  hideSubmit = false,
  onAdvance,
  canAdvance = false,
}: PracticeShellProps) {
  return (
    <section
      data-testid={`practice-shell-${problemId}`}
      data-variant={variant}
      className="flex flex-col gap-3 rounded-xl border border-[var(--border-subtle,rgba(255,255,255,0.06))] bg-card p-4"
    >
      <div>
        <div
          data-testid={`practice-shell-caption-${problemId}`}
          className={`text-[11px] uppercase tracking-[0.04em] font-medium ${VARIANT_ACCENT[variant]}`}
        >
          {VARIANT_LABEL[variant]} · Practice
        </div>
        <p
          className="mt-1 text-sm font-medium text-foreground"
          data-testid={`practice-shell-question-${problemId}`}
        >
          {question}
        </p>
      </div>

      {/* Variant-specific interactive surface — passed in by the host
          pane. The shell intentionally does not introspect or wrap it;
          the pane owns its Monaco / textarea / iframe lifecycle. */}
      <div data-testid={`practice-shell-surface-${problemId}`}>{surface}</div>

      {output ? (
        <div data-testid={`practice-shell-output-${problemId}`}>{output}</div>
      ) : null}

      {/* Shared explain-in-your-own-words rail — present for every
          variant (ТЗ §3 Slice 3 mandatory). Initial state mirrors the
          last-submit verdict: miss → expanded + auto-focused, correct
          → collapsed pill. */}
      <ExplainStep problemId={problemId} correct={correct} />

      <div className="flex items-center gap-2">
        {/* Shell submit is hidden when the inner surface owns the
            primary CTA (Python pane delegates to `<TaskRenderer>`'s
            own Run/Submit). Cross-variant explain + advance affordances
            still render below regardless. */}
        {hideSubmit ? null : (
          <Button
            type="button"
            size="sm"
            onClick={() => {
              void onSubmit();
            }}
            disabled={submitDisabled}
            data-testid={`practice-shell-submit-${problemId}`}
          >
            {submitLabel}
          </Button>
        )}
        {/* Next-task CTA — surfaced once the user has attempted the
            current task. Sitting next to Submit (not in the fixed
            footer) keeps the affordance in the user's gaze after the
            verdict lands. Phase B fix for Юрій-stuck-on-task-1. */}
        {onAdvance && canAdvance ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onAdvance}
            data-testid={`practice-shell-advance-${problemId}`}
          >
            Next task
          </Button>
        ) : null}
      </div>
    </section>
  );
}

export default PracticeShell;
