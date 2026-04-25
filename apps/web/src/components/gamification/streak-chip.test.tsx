/**
 * Tests for <StreakChip> (Phase 16c Bundle C — Subagent A).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StreakChip } from "./streak-chip";

describe("<StreakChip>", () => {
  it("renders the active state with emerald accent when streakDays > 0", () => {
    render(<StreakChip streakDays={7} freezesLeft={2} />);

    const days = screen.getByTestId("streak-chip-days");
    expect(days).toHaveTextContent("Streak 7 days");
    // Emerald tint via the --track-python token. We assert the class is
    // present rather than computing the resolved color — jsdom does not
    // resolve CSS custom properties.
    expect(days.className).toMatch(/track-python/);
  });

  it("renders calm copy in the muted state when streakDays === 0", () => {
    render(<StreakChip streakDays={0} freezesLeft={2} />);

    const days = screen.getByTestId("streak-chip-days");
    expect(days).toHaveTextContent(/no streak yet/i);
    expect(days.className).not.toMatch(/track-python/);
  });

  it("renders the no-freezes warm copy when freezesLeft === 0", () => {
    render(<StreakChip streakDays={5} freezesLeft={0} />);

    const freezes = screen.getByTestId("streak-chip-freezes");
    expect(freezes).toHaveTextContent(/no freezes this week/i);
    expect(freezes).toHaveTextContent(/keep going/i);
  });

  it("renders a freeze count when freezesLeft > 0", () => {
    render(<StreakChip streakDays={3} freezesLeft={2} />);

    const freezes = screen.getByTestId("streak-chip-freezes");
    expect(freezes).toHaveTextContent("2 freezes left");
  });
});
