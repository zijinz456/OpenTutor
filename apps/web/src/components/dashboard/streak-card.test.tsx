/**
 * Tests for <StreakCard> (Phase 16c Bundle B — Subagent B).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StreakCard } from "./streak-card";

describe("<StreakCard>", () => {
  it("shows the active streak with freezes remaining", () => {
    render(<StreakCard streakDays={7} freezesLeft={2} />);

    expect(screen.getByTestId("streak-card")).toBeInTheDocument();
    expect(screen.getByTestId("streak-card-days")).toHaveTextContent(
      "Streak 7 days",
    );
    expect(screen.getByTestId("streak-card-freezes")).toHaveTextContent(
      "2 freezes left this week",
    );
  });

  it("uses singular 'day' / 'freeze' grammar at 1", () => {
    render(<StreakCard streakDays={1} freezesLeft={1} />);
    expect(screen.getByTestId("streak-card-days")).toHaveTextContent(
      "Streak 1 day",
    );
    expect(screen.getByTestId("streak-card-freezes")).toHaveTextContent(
      "1 freeze left this week",
    );
  });

  it("renders calm new-account copy when streak is zero", () => {
    render(<StreakCard streakDays={0} freezesLeft={0} />);

    expect(screen.getByTestId("streak-card-days")).toHaveTextContent(
      "No streak yet",
    );
    expect(screen.getByTestId("streak-card-freezes")).toHaveTextContent(
      "Start a streak today",
    );
  });

  it("falls back to 'No freezes left' when an active streak runs out of freezes", () => {
    render(<StreakCard streakDays={5} freezesLeft={0} />);
    expect(screen.getByTestId("streak-card-freezes")).toHaveTextContent(
      "No freezes left",
    );
  });
});
