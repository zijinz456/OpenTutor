"use client";

/**
 * `<PomodoroSettings>` — collapsible settings panel for the Pomodoro
 * timer (Phase 14 T3). Sits next to the `<PanicToggle>` on the dashboard
 * header.
 *
 * Design notes
 * ------------
 * * **Writes localStorage immediately** via `updateSettings` — no Save
 *   button. ADHD-friendly: every flick of a slider is remembered without
 *   a dedicated commit step.
 * * **Collapsible, closed by default.** A summary pill ("Pomodoro: on 25/5/15")
 *   shows the current config at a glance; clicking expands the panel.
 *   Avoids cluttering the dashboard header when the feature is off.
 * * **Minute sliders with fixed ranges** per plan: focus 15-45 (step 5),
 *   short 3-10, long 10-30, cycles 2-6. Ranges chosen so users can't
 *   configure pathologically short (<15 min focus is just interruptions)
 *   or long (>45 min defeats the point of Pomodoro) sessions.
 */

import { useState } from "react";
import { usePomodoroStore } from "@/store/pomodoro";
import { cn } from "@/lib/utils";

interface Props {
  className?: string;
}

export function PomodoroSettings({ className }: Props) {
  const enabled = usePomodoroStore((s) => s.enabled);
  const focusMin = usePomodoroStore((s) => s.focusMin);
  const shortBreakMin = usePomodoroStore((s) => s.shortBreakMin);
  const longBreakMin = usePomodoroStore((s) => s.longBreakMin);
  const cyclesUntilLong = usePomodoroStore((s) => s.cyclesUntilLong);
  const chimeMuted = usePomodoroStore((s) => s.chimeMuted);
  const setEnabled = usePomodoroStore((s) => s.setEnabled);
  const updateSettings = usePomodoroStore((s) => s.updateSettings);

  const [open, setOpen] = useState(false);

  return (
    <div
      className={cn("relative inline-block text-xs", className)}
      data-testid="pomodoro-settings-root"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        data-testid="pomodoro-settings-summary"
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/60 px-3 py-1 font-medium hover:bg-muted"
        title="Pomodoro timer settings"
      >
        <span aria-hidden="true">🍅</span>
        <span>
          Pomodoro: {enabled
            ? `on ${focusMin}/${shortBreakMin}/${longBreakMin}`
            : "off"}
        </span>
      </button>

      {open && (
        <div
          data-testid="pomodoro-settings-panel"
          className="absolute right-0 top-full z-50 mt-2 w-72 rounded-xl border border-border bg-popover p-4 shadow-lg"
        >
          <label className="flex items-center justify-between gap-2">
            <span className="font-medium">Enabled</span>
            <input
              type="checkbox"
              data-testid="pomodoro-master-toggle"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="h-4 w-4"
            />
          </label>

          <SliderRow
            label="Focus (min)"
            testId="pomodoro-focus-slider"
            value={focusMin}
            min={15}
            max={45}
            step={5}
            onChange={(v) => updateSettings({ focusMin: v })}
          />
          <SliderRow
            label="Short break (min)"
            testId="pomodoro-short-slider"
            value={shortBreakMin}
            min={3}
            max={10}
            step={1}
            onChange={(v) => updateSettings({ shortBreakMin: v })}
          />
          <SliderRow
            label="Long break (min)"
            testId="pomodoro-long-slider"
            value={longBreakMin}
            min={10}
            max={30}
            step={5}
            onChange={(v) => updateSettings({ longBreakMin: v })}
          />
          <SliderRow
            label="Cycles until long"
            testId="pomodoro-cycles-slider"
            value={cyclesUntilLong}
            min={2}
            max={6}
            step={1}
            onChange={(v) => updateSettings({ cyclesUntilLong: v })}
          />

          <label className="mt-3 flex items-center justify-between gap-2">
            <span>Mute chime</span>
            <input
              type="checkbox"
              data-testid="pomodoro-mute-chime"
              checked={chimeMuted}
              onChange={(e) => updateSettings({ chimeMuted: e.target.checked })}
              className="h-4 w-4"
            />
          </label>
        </div>
      )}
    </div>
  );
}

interface SliderRowProps {
  label: string;
  testId: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}

function SliderRow({ label, testId, value, min, max, step, onChange }: SliderRowProps) {
  return (
    <div className="mt-3">
      <div className="mb-1 flex items-center justify-between">
        <span>{label}</span>
        <span className="tabular-nums font-medium">{value}</span>
      </div>
      <input
        type="range"
        data-testid={testId}
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
    </div>
  );
}
