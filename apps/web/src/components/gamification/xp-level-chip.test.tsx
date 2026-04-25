/**
 * Tests for <XpLevelChip> (Phase 16c Bundle C — Subagent A).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { XpLevelChip } from "./xp-level-chip";

describe("<XpLevelChip>", () => {
  it("renders tier label and total XP", () => {
    render(
      <XpLevelChip
        xpTotal={2450}
        levelTier="Silver II"
        levelName="Silver"
        levelProgressPct={45}
      />,
    );

    const tier = screen.getByTestId("xp-level-chip-tier");
    expect(tier).toHaveTextContent("[SILVER II]");
    expect(screen.getByText(/2,450 XP/)).toBeInTheDocument();
  });

  it("maps level names to hex prefixes 0x1..0x5", () => {
    const cases: Array<[string, string]> = [
      ["Bronze", "0x1"],
      ["Silver", "0x2"],
      ["Gold", "0x3"],
      ["Platinum", "0x4"],
      ["Diamond", "0x5"],
    ];
    for (const [name, prefix] of cases) {
      const { unmount } = render(
        <XpLevelChip
          xpTotal={0}
          levelTier={`${name} I`}
          levelName={name}
          levelProgressPct={0}
        />,
      );
      expect(screen.getByTestId("xp-level-chip-tier")).toHaveTextContent(
        prefix,
      );
      unmount();
    }
  });

  it("sets the progress bar width from levelProgressPct", () => {
    render(
      <XpLevelChip
        xpTotal={500}
        levelTier="Bronze III"
        levelName="Bronze"
        levelProgressPct={73}
      />,
    );
    const bar = screen.getByTestId("xp-level-chip-bar") as HTMLElement;
    expect(bar.style.width).toBe("73%");
  });

  it("shows the daily sub-line only when dailyGoalXp is provided", () => {
    const { rerender } = render(
      <XpLevelChip
        xpTotal={120}
        levelTier="Silver I"
        levelName="Silver"
        levelProgressPct={20}
      />,
    );
    expect(
      screen.queryByTestId("xp-level-chip-daily"),
    ).not.toBeInTheDocument();

    rerender(
      <XpLevelChip
        xpTotal={120}
        levelTier="Silver I"
        levelName="Silver"
        levelProgressPct={20}
        dailyGoalXp={200}
        dailyXpEarned={90}
      />,
    );
    const daily = screen.getByTestId("xp-level-chip-daily");
    expect(daily).toHaveTextContent("Today: 90 / 200 XP");
  });

  it("renders cleanly for a new account (xp=0)", () => {
    render(
      <XpLevelChip
        xpTotal={0}
        levelTier="Bronze I"
        levelName="Bronze"
        levelProgressPct={0}
      />,
    );
    expect(screen.getByTestId("xp-level-chip")).toBeInTheDocument();
    expect(screen.getByText(/0 XP/)).toBeInTheDocument();
    const bar = screen.getByTestId("xp-level-chip-bar") as HTMLElement;
    expect(bar.style.width).toBe("0%");
  });
});
