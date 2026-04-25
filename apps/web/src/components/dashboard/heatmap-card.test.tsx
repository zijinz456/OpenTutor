/**
 * Tests for <HeatmapCard> (Phase 16c Bundle B — Subagent B).
 */
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { HeatmapCard } from "./heatmap-card";

describe("<HeatmapCard>", () => {
  it("renders the header label and the inner sparse heatmap grid", () => {
    render(
      <HeatmapCard
        tiles={[{ date: "2026-04-25", xp: 30 }]}
        todayUtc="2026-04-25"
      />,
    );
    expect(screen.getByTestId("heatmap-card")).toBeInTheDocument();
    expect(screen.getByText(/Last 365 days/)).toBeInTheDocument();

    const grid = screen.getByTestId("heatmap-card-grid");
    expect(within(grid).getByTestId("sparse-heatmap")).toBeInTheDocument();
  });

  it("renders calm empty state when no tiles are passed", () => {
    render(<HeatmapCard tiles={[]} todayUtc="2026-04-25" />);
    expect(screen.getByTestId("heatmap-card")).toBeInTheDocument();
    // No active tile testids in DOM.
    expect(
      screen.queryByTestId("heatmap-tile-2026-04-25"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("sparse-heatmap")).toBeInTheDocument();
  });

  it("includes a 'today' caption per spec", () => {
    render(<HeatmapCard tiles={[]} todayUtc="2026-04-25" />);
    expect(screen.getByText(/today/i)).toBeInTheDocument();
  });
});
