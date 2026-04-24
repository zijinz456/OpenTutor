import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TodayToolsPopover } from "./today-tools-popover";
import { useBadDayStore } from "@/store/bad-day";
import { usePanicStore } from "@/store/panic";
import { usePomodoroStore } from "@/store/pomodoro";

const getFreezeStatusMock = vi.fn();

vi.mock("@/lib/api/freeze", () => ({
  getFreezeStatus: (...args: unknown[]) => getFreezeStatusMock(...args),
}));

describe("<TodayToolsPopover>", () => {
  beforeEach(() => {
    window.localStorage.clear();
    getFreezeStatusMock.mockReset();
    getFreezeStatusMock.mockResolvedValue({
      quota_remaining: 2,
      weekly_used: 1,
      active_freezes: [],
    });
    usePanicStore.setState({ enabled: false, enabledAt: null });
    useBadDayStore.setState({ active: false, activated_date: "" });
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

  it("shows all four tools when opened", async () => {
    const user = userEvent.setup();
    render(<TodayToolsPopover />);

    await user.click(screen.getByTestId("today-tools-trigger"));

    expect(screen.getByText("Quiet mode")).toBeInTheDocument();
    expect(screen.getByText("Easy mode")).toBeInTheDocument();
    expect(screen.getByTestId("today-tools-pomodoro")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("today-tools-freezes")).toHaveTextContent(
        "2 freezes left",
      );
    });
  });

  it("toggles quiet mode from the popover", async () => {
    const user = userEvent.setup();
    render(<TodayToolsPopover />);

    await user.click(screen.getByTestId("today-tools-trigger"));
    const quietToggle = screen.getByTestId("today-tools-quiet-toggle");
    expect(quietToggle).toHaveAttribute("aria-pressed", "false");

    await user.click(quietToggle);

    expect(quietToggle).toHaveAttribute("aria-pressed", "true");
  });
});
