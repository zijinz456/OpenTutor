import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PomodoroSettings } from "./PomodoroSettings";
import { usePomodoroStore } from "@/store/pomodoro";

/**
 * PomodoroSettings tests (Phase 14 T3).
 *
 * The summary pill is collapsed by default; we click it to open the
 * panel before toggling inputs. Both tests assert the store was
 * updated AND localStorage was written — the store's action is the
 * single source of truth for persistence.
 */

describe("<PomodoroSettings>", () => {
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

  it("toggling master switch updates the store", () => {
    render(<PomodoroSettings />);
    fireEvent.click(screen.getByTestId("pomodoro-settings-summary"));

    const toggle = screen.getByTestId("pomodoro-master-toggle") as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    expect(usePomodoroStore.getState().enabled).toBe(false);

    fireEvent.click(toggle);
    expect(usePomodoroStore.getState().enabled).toBe(true);

    // Persistence contract: setEnabled writes to localStorage.
    const raw = window.localStorage.getItem("pomodoro_settings_v1");
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw as string).enabled).toBe(true);
  });

  it("focus-duration slider change updates focusMin in store + localStorage", () => {
    render(<PomodoroSettings />);
    fireEvent.click(screen.getByTestId("pomodoro-settings-summary"));

    const slider = screen.getByTestId("pomodoro-focus-slider") as HTMLInputElement;
    expect(slider.value).toBe("25");

    fireEvent.change(slider, { target: { value: "35" } });
    expect(usePomodoroStore.getState().focusMin).toBe(35);

    const raw = window.localStorage.getItem("pomodoro_settings_v1");
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw as string).focusMin).toBe(35);
  });
});
