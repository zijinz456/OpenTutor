"use client";

/**
 * `<BrutalTimerRing>` — pure CSS countdown ring for the Brutal runner
 * (Phase 6 T3).
 *
 * Why CSS-only (not `setInterval` / `requestAnimationFrame`)?
 * ----------------------------------------------------------
 * * Zero React re-renders during the countdown — cheaper and smoother.
 * * `animationPlayState` gives us pause/resume for free when the tab
 *   loses focus (§Architecture timer block of the phase plan). A JS
 *   clock would need to persist elapsed-ms and resume with a new timer.
 * * `onAnimationEnd` fires exactly once when the animation reaches
 *   `forwards` steady-state, giving us a reliable timeout signal
 *   without any drift math.
 *
 * Remount-to-restart
 * ------------------
 * Browsers do not restart a CSS animation just because the duration
 * changes. The parent passes `key={cardId + attempts[cardId]}` so React
 * unmounts+remounts this component on every card change AND every retry
 * of the same card; the SVG starts at `stroke-dashoffset: 0` again and
 * animates back to `283` (full circumference).
 *
 * Pause plumbing
 * --------------
 * The parent owns `visibilitychange`. It mutates `animationPlayState` by
 * toggling a className on the SVG via `paused` prop — we keep the flag
 * at the leaf so the effect chain is explicit.
 */

import { useEffect, useRef } from "react";

interface BrutalTimerRingProps {
  timeoutMs: number;
  paused: boolean;
  onTimeout: () => void;
}

// SVG geometry: r=45 gives circumference ≈ 283 (2π*45). Hard-coding
// the exact number into the CSS keyframe (via the `brutal-timer-ring`
// class in globals.css) keeps the animation independent of the
// component's rendered size.
const RADIUS = 45;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS; // ≈ 283

export function BrutalTimerRing({
  timeoutMs,
  paused,
  onTimeout,
}: BrutalTimerRingProps) {
  const circleRef = useRef<SVGCircleElement | null>(null);

  // Toggle paused state via a style mutation (not a class) because
  // animationPlayState is the single cleanest lever and we can't rely on
  // className swaps during an in-flight animation without triggering a
  // restart in some browsers.
  useEffect(() => {
    const el = circleRef.current;
    if (!el) return;
    el.style.animationPlayState = paused ? "paused" : "running";
  }, [paused]);

  return (
    <svg
      viewBox="0 0 100 100"
      className="size-10"
      data-testid="brutal-timer-ring"
      aria-hidden="true"
    >
      {/* Background track */}
      <circle
        cx="50"
        cy="50"
        r={RADIUS}
        fill="none"
        stroke="currentColor"
        strokeWidth="6"
        className="text-muted/40"
      />
      {/* Animated foreground: stroke-dashoffset goes 0 → CIRCUMFERENCE
          (fully invisible) across `--brutal-timeout-ms`. The keyframe
          is declared in globals.css to keep this component pure JSX. */}
      <circle
        ref={circleRef}
        cx="50"
        cy="50"
        r={RADIUS}
        fill="none"
        stroke="currentColor"
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={CIRCUMFERENCE}
        strokeDashoffset={0}
        transform="rotate(-90 50 50)"
        className="brutal-timer-ring-stroke text-amber-500"
        style={
          {
            // Passing the duration via a CSS variable lets us change the
            // per-card timeout without recompiling styles.
            "--brutal-timeout-ms": `${timeoutMs}ms`,
          } as React.CSSProperties
        }
        onAnimationEnd={onTimeout}
      />
    </svg>
  );
}
