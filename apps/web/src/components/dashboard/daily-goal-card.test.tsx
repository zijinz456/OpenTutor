/**
 * Tests for <DailyGoalCard> (Phase 16c Bundle B — Subagent B).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DailyGoalCard } from "./daily-goal-card";

describe("<DailyGoalCard>", () => {
  it("renders progress text and a half-filled bar when below goal", () => {
    render(<DailyGoalCard dailyGoalXp={200} dailyXpEarned={100} />);

    expect(screen.getByTestId("daily-goal-card")).toBeInTheDocument();
    expect(screen.getByTestId("daily-goal-card-progress")).toHaveTextContent(
      "100 / 200 XP",
    );
    const bar = screen.getByTestId("daily-goal-card-bar") as HTMLElement;
    expect(bar.style.width).toBe("50%");
    // Met badge must NOT show below goal.
    expect(screen.queryByTestId("daily-goal-card-met")).not.toBeInTheDocument();
  });

  it("shows the supportive starter copy for a new account (goal=10, earned=0)", () => {
    render(<DailyGoalCard dailyGoalXp={10} dailyXpEarned={0} />);
    expect(screen.getByTestId("daily-goal-card-progress")).toHaveTextContent(
      "Earn 10 XP today to start",
    );
    const bar = screen.getByTestId("daily-goal-card-bar") as HTMLElement;
    expect(bar.style.width).toBe("0%");
  });

  it("shows 'Daily goal met' when earned >= goal", () => {
    render(<DailyGoalCard dailyGoalXp={200} dailyXpEarned={250} />);
    expect(screen.getByTestId("daily-goal-card-met")).toHaveTextContent(
      "Daily goal met",
    );
    const bar = screen.getByTestId("daily-goal-card-bar") as HTMLElement;
    // Fill clamps to 100% even when overshooting.
    expect(bar.style.width).toBe("100%");
  });

  it("renders a 0% bar without crashing when goal is 0", () => {
    render(<DailyGoalCard dailyGoalXp={0} dailyXpEarned={0} />);
    const bar = screen.getByTestId("daily-goal-card-bar") as HTMLElement;
    expect(bar.style.width).toBe("0%");
    // Met badge must not show when goal is 0 (no goal to meet).
    expect(screen.queryByTestId("daily-goal-card-met")).not.toBeInTheDocument();
  });
});
