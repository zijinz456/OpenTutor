"use client";

/**
 * `<HackingPane>` — Slice 3 Hacking-track wrapper.
 *
 * Per ТЗ §3 Slice 3 item #3: "Hacking mission → Juice Shop iframe +
 * proof pane." The pane hosts:
 *
 *   - an `<iframe>` pointing at the live Juice Shop instance (the
 *     compose stack already exposes `juiceshop:3000` / `:42-...`
 *     depending on the room — see `juice_shop_url`),
 *   - a proof input (text or URL of the captured flag, depending on
 *     the room's verification mode),
 *   - per-room verification verdict slotted into `<PracticeShell>`'s
 *     output region.
 *
 * Phase A scope
 * -------------
 * Phase 12 owns the live Juice Shop wiring + proof-verification API.
 * This pane ships the *shape* (iframe + proof input + submit + output
 * region) so the existing Phase 12 backend plugs in without touching
 * the surface. Codex B's hacking content backfill (G1 in the V1 gate)
 * is the gating work for any live demo; we are NOT shipping new
 * hacking content from Phase A.
 *
 * Sandboxed iframe — `sandbox="allow-scripts allow-same-origin
 * allow-forms"` is the existing Phase 12 contract; do not loosen
 * without consulting docs/qa/v1_release_readiness.md G1.
 */

import { useState } from "react";
import { PracticeShell } from "./practice-shell";

export interface HackingPaneProps {
  /** Stable problem/task id — explain rail key + submit handler scope. */
  problemId: string;
  /** Visible task prompt — usually the room's challenge brief. */
  question: string;
  /** Juice Shop URL for this room. Defaults to the local compose
   *  stack at `http://localhost:3000` — production sets this from the
   *  room's metadata (different rooms can target different ports /
   *  scenarios). */
  juiceShopUrl?: string;
  /** Initial proof string (e.g. resuming a draft / partial flag). */
  initialProof?: string;
  /** Whether the last submission was correct — passes through to the
   *  shell's explain rail. */
  correct?: boolean;
  /** Submit handler. Receives the proof string; the host owns the
   *  network call (Phase 12 proof-verification endpoint). */
  onSubmit?: (proof: string) => void | Promise<void>;
  /** Optional verdict block — Phase 12 verification result rendered
   *  by the host once submit returns. */
  output?: React.ReactNode;
}

export function HackingPane({
  problemId,
  question,
  juiceShopUrl = "http://localhost:3000",
  initialProof = "",
  correct = false,
  onSubmit,
  output,
}: HackingPaneProps) {
  const [proof, setProof] = useState<string>(initialProof);

  return (
    <PracticeShell
      problemId={problemId}
      variant="hacking"
      question={question}
      surface={
        <div className="flex flex-col gap-2">
          <iframe
            data-testid={`hacking-pane-iframe-${problemId}`}
            src={juiceShopUrl}
            title="Juice Shop training environment"
            sandbox="allow-scripts allow-same-origin allow-forms"
            className="aspect-[16/10] w-full rounded-md border border-border bg-muted/30"
          />
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              Proof — paste the captured flag, payload, or URL.
            </span>
            <input
              data-testid={`hacking-pane-proof-${problemId}`}
              type="text"
              value={proof}
              onChange={(e) => setProof(e.target.value)}
              placeholder="e.g. {flag:...} or POST body / screenshot URL"
              className="w-full rounded-md border border-border bg-muted/30 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring font-mono"
            />
          </label>
        </div>
      }
      output={output}
      correct={correct}
      onSubmit={() => onSubmit?.(proof)}
      submitDisabled={proof.trim().length === 0}
      submitLabel="Submit checkpoint & advance"
    />
  );
}

export default HackingPane;
