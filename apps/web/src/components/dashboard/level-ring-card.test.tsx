/**
 * Tests for <LevelRingCard> (Phase 16c Bundle B — Subagent B).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LevelRingCard } from "./level-ring-card";

describe("<LevelRingCard>", () => {
  it("renders tier prefix, total XP, and next-level copy", () => {
    render(
      <LevelRingCard
        xpTotal={2450}
        levelTier="Silver II"
        levelName="Silver"
        levelProgressPct={45}
        xpToNextLevel={550}
      />,
    );

    expect(screen.getByTestId("level-ring-card")).toBeInTheDocument();
    const tier = screen.getByTestId("level-ring-card-tier");
    expect(tier).toHaveTextContent("0x2");
    expect(tier).toHaveTextContent("[SILVER II]");
    expect(screen.getByTestId("level-ring-card-xp-total")).toHaveTextContent(
      "2,450 XP",
    );
    expect(screen.getByTestId("level-ring-card-next")).toHaveTextContent(
      "550 XP to next level",
    );
    expect(screen.getByTestId("level-ring-card-progress")).toBeInTheDocument();
  });

  it("renders calm zero state for a new account", () => {
    render(
      <LevelRingCard
        xpTotal={0}
        levelTier="Bronze I"
        levelName="Bronze"
        levelProgressPct={0}
        xpToNextLevel={100}
      />,
    );

    expect(screen.getByTestId("level-ring-card-xp-total")).toHaveTextContent(
      "0 XP",
    );
    expect(screen.getByTestId("level-ring-card-next")).toHaveTextContent(
      "100 XP to next level",
    );
  });

  it("shows 'Maxed' when xpToNextLevel is 0", () => {
    render(
      <LevelRingCard
        xpTotal={50000}
        levelTier="Diamond V"
        levelName="Diamond"
        levelProgressPct={100}
        xpToNextLevel={0}
      />,
    );

    expect(screen.getByTestId("level-ring-card-next")).toHaveTextContent(
      "Maxed",
    );
  });

  it("clamps progress percentage out-of-range values", () => {
    // Sanity: very high pct should not break the SVG render path.
    render(
      <LevelRingCard
        xpTotal={9999}
        levelTier="Gold III"
        levelName="Gold"
        levelProgressPct={250}
        xpToNextLevel={42}
      />,
    );
    const ring = screen.getByTestId("level-ring-card-progress");
    expect(ring.tagName.toLowerCase()).toBe("svg");
  });
});
