"use client";

/**
 * `<EnglishPane>` — Slice 3 English-track wrapper.
 *
 * Per ТЗ §3 Slice 3 item #2: "English mission → answer textarea + voice
 * button." The pane hosts:
 *
 *   - a `<textarea>` for the typed answer (shell-internal state),
 *   - a `<VoiceButton>` (Phase 8 Whisper integration — placeholder
 *     here, lifted from `apps/web/src/components/voice/*` when the
 *     mission router begins to dispatch English missions),
 *   - the Phase 5 Interviewer SSE stream rendered as the `output` slot
 *     of `<PracticeShell>` once a session starts.
 *
 * Phase A scope
 * -------------
 * The Interview SSE wiring is out of scope — that's an entire bundle
 * of work owned by Phase 5 / 16-recap. This pane ships the *shape*
 * (textarea + voice trigger + output region) so future English
 * missions plug in without fighting the layout. The voice button is
 * a non-functional stub today; it documents the slot. ТЗ §3 Slice 3
 * acceptance is about pattern-readiness across variants, not full
 * live demo of every track in Phase A.
 */

import { useState } from "react";
import { Mic } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PracticeShell } from "./practice-shell";

export interface EnglishPaneProps {
  /** Stable problem/task id — explain rail key + submit handler scope. */
  problemId: string;
  /** Visible task prompt. */
  question: string;
  /** Optional initial textarea value (e.g. resuming a draft). */
  initialAnswer?: string;
  /** Whether the last submission was correct — passes through to the
   *  shell's explain rail. */
  correct?: boolean;
  /** Submit handler. Receives the final answer string; the host owns
   *  the network call (Phase 5 Interviewer SSE start, etc.). */
  onSubmit?: (answer: string) => void | Promise<void>;
  /** Optional output region — usually the streaming Interviewer
   *  rubric/transcript when the SSE is live. */
  output?: React.ReactNode;
}

export function EnglishPane({
  problemId,
  question,
  initialAnswer = "",
  correct = false,
  onSubmit,
  output,
}: EnglishPaneProps) {
  const [answer, setAnswer] = useState<string>(initialAnswer);
  const [voiceActive, setVoiceActive] = useState<boolean>(false);

  // Phase 8 voice integration is wired by the mission router when
  // English missions ship. The button is intentionally a non-functional
  // toggle today — it documents the slot for later. Clicking flips a
  // local "active" indicator so the visual state is testable.
  const handleVoiceToggle = () => {
    setVoiceActive((prev) => !prev);
    // TODO(phase-5-english-missions): replace with the
    // `useWhisperRecorder` hook from `components/voice/recorder` when
    // the English mission seed lands.
  };

  return (
    <PracticeShell
      problemId={problemId}
      variant="english"
      question={question}
      surface={
        <div className="flex flex-col gap-2">
          <textarea
            data-testid={`english-pane-textarea-${problemId}`}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="Type your answer, or press the mic to dictate."
            rows={5}
            className="w-full resize-y rounded-md border border-border bg-muted/30 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant={voiceActive ? "default" : "outline"}
              onClick={handleVoiceToggle}
              data-testid={`english-pane-voice-${problemId}`}
              aria-pressed={voiceActive}
              aria-label={voiceActive ? "Stop dictation" : "Start dictation"}
            >
              <Mic aria-hidden="true" className="size-4" />
              <span className="ml-1">{voiceActive ? "Listening" : "Dictate"}</span>
            </Button>
          </div>
        </div>
      }
      output={output}
      correct={correct}
      onSubmit={() => onSubmit?.(answer)}
      submitDisabled={answer.trim().length === 0}
      submitLabel="Submit checkpoint & advance"
    />
  );
}

export default EnglishPane;
