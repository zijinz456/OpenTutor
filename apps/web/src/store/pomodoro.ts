/**
 * Zustand store for the optional Pomodoro timer (Phase 14 T3,
 * plan `plan/adhd_ux_full_phase14.md`).
 *
 * Design notes
 * ------------
 * * **Persist SETTINGS only, not running timer state.** The plan is
 *   explicit that sessions start fresh per page load ("no resume
 *   across tabs / refreshes"). Persisting phase/phaseEndsAt would
 *   make the tab that was left open overnight fire a long-expired
 *   chime the moment the user came back. Settings (on/off, durations,
 *   mute) DO persist — user preference, not ephemeral state.
 * * **Durations stored in minutes**, converted to ms on phase start.
 *   Keeps the settings UI honest (sliders in minutes) and avoids
 *   an extra unit-conversion layer between UI and store.
 * * **`advancePhase()` is pure state math.** It does not schedule a
 *   timer — the owning component runs a 1s `setInterval` and calls
 *   `advancePhase()` when `Date.now() >= phaseEndsAt`. This keeps the
 *   store deterministic and trivially testable with fake timers.
 * * **Cycle counting:** `completedCycles` increments when a focus
 *   block completes. After `cyclesUntilLong` focus blocks, the next
 *   break is a long break and the counter resets to 0.
 * * **SSR safety.** Same pattern as `panic.ts`: every `window` touch
 *   is `typeof window`-guarded. Initial state on server = defaults.
 */

import { create } from "zustand";

export type PomodoroPhase = "idle" | "focus" | "short_break" | "long_break";

export interface PomodoroSettings {
  enabled: boolean;
  focusMin: number;
  shortBreakMin: number;
  longBreakMin: number;
  cyclesUntilLong: number;
  chimeMuted: boolean;
}

export interface PomodoroState extends PomodoroSettings {
  phase: PomodoroPhase;
  /** Date.now() when current phase started. 0 while idle. */
  phaseStartedAt: number;
  /** Date.now() + phase duration. 0 while idle. */
  phaseEndsAt: number;
  /** Focus blocks completed in the current long-break cycle (0..cyclesUntilLong). */
  completedCycles: number;

  setEnabled: (on: boolean) => void;
  updateSettings: (patch: Partial<PomodoroSettings>) => void;
  startFocus: () => void;
  advancePhase: () => void;
  pauseSession: () => void;
  toggleChime: () => void;
}

const STORAGE_KEY = "pomodoro_settings_v1";

const DEFAULT_SETTINGS: PomodoroSettings = {
  enabled: false,
  focusMin: 25,
  shortBreakMin: 5,
  longBreakMin: 15,
  cyclesUntilLong: 4,
  chimeMuted: false,
};

/** Read persisted settings. Returns defaults on SSR or malformed JSON. */
function readInitialSettings(): PomodoroSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return DEFAULT_SETTINGS;
  try {
    const parsed = JSON.parse(raw) as Partial<PomodoroSettings>;
    // Shallow-merge: tolerate older payloads missing newer keys.
    return { ...DEFAULT_SETTINGS, ...parsed };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

/** Write the settings slice to localStorage. No-op under SSR. */
function writeSettings(settings: PomodoroSettings): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

/** Extract just the persisted settings out of full state. */
function pickSettings(s: PomodoroSettings): PomodoroSettings {
  return {
    enabled: s.enabled,
    focusMin: s.focusMin,
    shortBreakMin: s.shortBreakMin,
    longBreakMin: s.longBreakMin,
    cyclesUntilLong: s.cyclesUntilLong,
    chimeMuted: s.chimeMuted,
  };
}

export const usePomodoroStore = create<PomodoroState>((set, get) => ({
  ...readInitialSettings(),
  phase: "idle",
  phaseStartedAt: 0,
  phaseEndsAt: 0,
  completedCycles: 0,

  setEnabled: (on) => {
    const next = { ...pickSettings(get()), enabled: on };
    writeSettings(next);
    // Turning the feature off also pauses any running phase — otherwise
    // the overlay would vanish mid-countdown and the break chime would
    // still try to fire.
    if (!on) {
      set({
        enabled: false,
        phase: "idle",
        phaseStartedAt: 0,
        phaseEndsAt: 0,
        completedCycles: 0,
      });
    } else {
      set({ enabled: true });
    }
  },

  updateSettings: (patch) => {
    const merged = { ...pickSettings(get()), ...patch };
    writeSettings(merged);
    set(merged);
  },

  startFocus: () => {
    const { focusMin } = get();
    const now = Date.now();
    set({
      phase: "focus",
      phaseStartedAt: now,
      phaseEndsAt: now + focusMin * 60_000,
    });
  },

  advancePhase: () => {
    const s = get();
    const now = Date.now();
    // focus → break (short or long depending on completed cycles)
    if (s.phase === "focus") {
      const nextCycles = s.completedCycles + 1;
      const isLong = nextCycles >= s.cyclesUntilLong;
      const breakMin = isLong ? s.longBreakMin : s.shortBreakMin;
      set({
        phase: isLong ? "long_break" : "short_break",
        phaseStartedAt: now,
        phaseEndsAt: now + breakMin * 60_000,
        // Long break resets the cycle counter so the next round starts
        // fresh at 0; short break just keeps the accumulator.
        completedCycles: isLong ? 0 : nextCycles,
      });
      return;
    }
    // any break → next focus
    if (s.phase === "short_break" || s.phase === "long_break") {
      set({
        phase: "focus",
        phaseStartedAt: now,
        phaseEndsAt: now + s.focusMin * 60_000,
      });
      return;
    }
    // idle → no-op (caller should use startFocus)
  },

  pauseSession: () => {
    set({
      phase: "idle",
      phaseStartedAt: 0,
      phaseEndsAt: 0,
    });
  },

  toggleChime: () => {
    const next = { ...pickSettings(get()), chimeMuted: !get().chimeMuted };
    writeSettings(next);
    set({ chimeMuted: next.chimeMuted });
  },
}));
