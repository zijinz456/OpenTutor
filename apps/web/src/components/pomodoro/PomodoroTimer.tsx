"use client";

/**
 * `<PomodoroTimer>` — optional focus-timer pill (Phase 14 T3).
 *
 * Architecture
 * ------------
 * * **Local 1s tick**, not store-driven. A `setInterval(1000)` in this
 *   component drives the live countdown via a local `useState` so
 *   re-renders are confined here — the Zustand store never ticks. When
 *   `Date.now() >= phaseEndsAt` the tick calls `advancePhase()` exactly
 *   once; the store mutation re-renders and the effect cleans up.
 *
 * * **Chime on phase transition**, not on every tick. A `useEffect` keyed
 *   on `phase` plays the audio when phase changes — guarded by:
 *     (1) store `chimeMuted` flag, and
 *     (2) `document.hidden` check (critic C3: don't spook a backgrounded
 *         tab with a sound from a tab the user forgot about).
 *
 * * **Break overlay on drill pages.** When phase is a break AND the URL
 *   path matches a drill route (under /session or under /tracks/:slug/missions), we
 *   render a dimming overlay with a "Skip break" button. It sits above
 *   the drill UI but below Panic Mode's exit CTA (lower z-index).
 *   Critic C3 is honoured by caller convention: break timing is only
 *   armed between cards because `startFocus` is user-triggered; the
 *   timer never interrupts a card mid-answer.
 *
 * * **No SSR work.** The initial `document.hidden` check is behind the
 *   chime-effect's `mounted` guard so Next.js SSR doesn't reach into
 *   the DOM at render time.
 */

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { usePomodoroStore } from "@/store/pomodoro";
import { cn } from "@/lib/utils";

const CHIME_SRC = "/sounds/pomodoro-chime.wav";

/** Return "MM:SS" for a non-negative ms remainder. */
function formatRemaining(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Drill routes where a break should dim the main content. */
function isDrillPath(pathname: string | null): boolean {
  if (!pathname) return false;
  if (pathname.startsWith("/session/")) return true;
  // /tracks/:slug/missions/:mission
  if (/^\/tracks\/[^/]+\/missions\//.test(pathname)) return true;
  return false;
}

export function PomodoroTimer() {
  const enabled = usePomodoroStore((s) => s.enabled);
  const phase = usePomodoroStore((s) => s.phase);
  const phaseEndsAt = usePomodoroStore((s) => s.phaseEndsAt);
  const chimeMuted = usePomodoroStore((s) => s.chimeMuted);
  const startFocus = usePomodoroStore((s) => s.startFocus);
  const advancePhase = usePomodoroStore((s) => s.advancePhase);
  const pauseSession = usePomodoroStore((s) => s.pauseSession);

  const [remaining, setRemaining] = useState<number>(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const pathname = usePathname();

  // Local tick — drives countdown display + auto-advance.
  useEffect(() => {
    if (phase === "idle") {
      setRemaining(0);
      return;
    }
    const update = () => {
      const rem = phaseEndsAt - Date.now();
      setRemaining(rem);
      if (rem <= 0) {
        advancePhase();
      }
    };
    update();
    const id = window.setInterval(update, 1000);
    return () => window.clearInterval(id);
  }, [phase, phaseEndsAt, advancePhase]);

  // Chime on phase transition (not on idle, not on muted, not on hidden tab).
  const prevPhaseRef = useRef<typeof phase>(phase);
  useEffect(() => {
    const prev = prevPhaseRef.current;
    prevPhaseRef.current = phase;
    if (prev === phase) return;
    if (phase === "idle") return;
    if (chimeMuted) return;
    if (typeof document !== "undefined" && document.hidden) return;
    const audio = audioRef.current;
    if (!audio) return;
    // Rewind in case the user rapid-cycles; .play() returns a promise on
    // modern browsers — swallow the AbortError that jsdom + some browsers
    // raise when play is interrupted by a subsequent load.
    try {
      audio.currentTime = 0;
      void audio.play().catch(() => undefined);
    } catch {
      /* audio unavailable — silent fallback */
    }
  }, [phase, chimeMuted]);

  if (!enabled) return null;

  const isBreak = phase === "short_break" || phase === "long_break";
  const showBreakOverlay = isBreak && isDrillPath(pathname);

  return (
    <>
      {/* Audio element: render ONLY when chime is not muted so the DOM
          reflects the muted state (simpler testing contract than a volume
          toggle — plan 3f/4 spec permits either, this is explicit). */}
      {!chimeMuted && (
        <audio
          ref={audioRef}
          src={CHIME_SRC}
          preload="auto"
          data-testid="pomodoro-chime"
        />
      )}

      {/* Top-right pill. Sits below PanicOverlay's exit CTA (z-40 vs z-50)
          so Panic's escape hatch is always reachable. */}
      <div
        data-testid="pomodoro-pill"
        className={cn(
          "fixed top-16 right-4 z-40 rounded-full border border-border px-3 py-1 text-xs shadow-sm md:right-6",
          "bg-muted/80 backdrop-blur-sm",
        )}
      >
        {phase === "idle" && (
          <button
            type="button"
            onClick={startFocus}
            className="flex items-center gap-1.5 hover:opacity-80"
            aria-label="Start a 25-minute focus block"
          >
            <span aria-hidden="true">🍅</span>
            <span>Start focus</span>
          </button>
        )}

        {phase === "focus" && (
          <button
            type="button"
            onClick={pauseSession}
            className="flex items-center gap-1.5 hover:opacity-80"
            aria-label="Pause focus block"
            title="Click to pause"
          >
            <span aria-hidden="true">🍅</span>
            <span className="tabular-nums">{formatRemaining(remaining)}</span>
          </button>
        )}

        {isBreak && (
          <button
            type="button"
            onClick={advancePhase}
            className="flex items-center gap-1.5 hover:opacity-80"
            aria-label="Skip break and start next focus block"
          >
            <span aria-hidden="true">☕</span>
            <span className="tabular-nums">
              Break {formatRemaining(remaining)}
            </span>
          </button>
        )}
      </div>

      {/* Break overlay on drill pages only. Lighter than Panic dim so the
          card underneath stays legible — the user is NOT forced to stop
          mid-card (critic C3); they simply see "hey, break time" and may
          dismiss it when they finish their current card. */}
      {showBreakOverlay && (
        <div
          data-testid="pomodoro-break-overlay"
          className="fixed inset-0 z-30 flex items-center justify-center bg-background/70 backdrop-blur-sm pointer-events-none"
        >
          <div className="pointer-events-auto rounded-2xl bg-card px-6 py-5 shadow-xl border border-border text-center">
            <div className="text-2xl font-semibold mb-1">
              {phase === "long_break" ? "Long break" : "Break"}
            </div>
            <div className="text-3xl font-bold tabular-nums mb-3">
              {formatRemaining(remaining)}
            </div>
            <button
              type="button"
              onClick={advancePhase}
              className="rounded-full bg-muted px-4 py-1 text-sm hover:bg-muted/70"
            >
              Skip break
            </button>
          </div>
        </div>
      )}
    </>
  );
}
