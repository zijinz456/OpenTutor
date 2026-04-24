import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { PomodoroTimer } from "./PomodoroTimer";
import { usePomodoroStore } from "@/store/pomodoro";

/**
 * PomodoroTimer tests (Phase 14 T3).
 *
 * We drive the Zustand store via `.setState()` rather than click through
 * `<PomodoroSettings>` to isolate the timer's render logic from the
 * settings panel. `usePathname` is mocked because the component reads
 * the current URL for the drill-route break-overlay gate.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/", // non-drill route by default
}));

describe("<PomodoroTimer>", () => {
  beforeEach(() => {
    window.localStorage.clear();
    usePomodoroStore.setState({
      enabled: false,
      focusMin: 25,
      shortBreakMin: 5,
      longBreakMin: 15,
      cyclesUntilLong: 4,
      chimeMuted: false,
      phase: "idle",
      phaseStartedAt: 0,
      phaseEndsAt: 0,
      completedCycles: 0,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders 'Start focus' button in idle state when enabled", () => {
    usePomodoroStore.setState({ enabled: true });
    render(<PomodoroTimer />);
    const pill = screen.getByTestId("pomodoro-pill");
    expect(pill).toBeInTheDocument();
    expect(pill).toHaveTextContent(/start focus/i);
  });

  it("renders countdown (MM:SS) in focus state", () => {
    const fakeNow = 2_000_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(fakeNow);
    usePomodoroStore.setState({
      enabled: true,
      phase: "focus",
      phaseStartedAt: fakeNow,
      // 2 minutes 3 seconds remaining → 2:03
      phaseEndsAt: fakeNow + (2 * 60 + 3) * 1000,
    });
    render(<PomodoroTimer />);
    expect(screen.getByTestId("pomodoro-pill")).toHaveTextContent("2:03");
  });

  it("chime audio element present when enabled and not muted", () => {
    usePomodoroStore.setState({ enabled: true, chimeMuted: false });
    render(<PomodoroTimer />);
    const audio = screen.getByTestId("pomodoro-chime") as HTMLAudioElement;
    expect(audio).toBeInTheDocument();
    expect(audio.getAttribute("src")).toContain("pomodoro-chime.wav");
  });

  it("chimeMuted hides the audio element", () => {
    usePomodoroStore.setState({ enabled: true, chimeMuted: true });
    render(<PomodoroTimer />);
    expect(screen.queryByTestId("pomodoro-chime")).not.toBeInTheDocument();
    // Pill itself is still rendered so user can see/control the timer.
    expect(screen.getByTestId("pomodoro-pill")).toBeInTheDocument();
  });
});

/* Use `act` in an unused assertion to avoid unused-import warnings in
   environments that don't report on unused bindings. `act` is kept
   imported so future tests can exercise tick-driven transitions. */
void act;
