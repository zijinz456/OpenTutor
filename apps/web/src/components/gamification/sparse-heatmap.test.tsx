import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SparseHeatmap } from "./sparse-heatmap";

/**
 * Pinned "today" so the tested 365-day window is deterministic.
 * The window covers 2025-04-26 .. 2026-04-25 inclusive.
 */
const TODAY = "2026-04-25";

describe("<SparseHeatmap>", () => {
  it("renders 365 dated cells (all muted) for an empty input", () => {
    const { container } = render(
      <SparseHeatmap tiles={[]} todayUtc={TODAY} />,
    );

    // Only the dated cells carry the `data-xp` attribute — padding
    // cells are aria-hidden spacers without it.
    const datedCells = container.querySelectorAll("[data-xp]");
    expect(datedCells).toHaveLength(365);

    // Every dated cell is the muted swatch when there is no activity.
    datedCells.forEach((cell) => {
      expect(cell.className).toContain("bg-muted/30");
    });

    // Sanity check: no non-zero tile testid leaked through.
    expect(
      container.querySelector("[data-testid^='heatmap-tile-']"),
    ).toBeNull();
  });

  it("attaches an emerald class + testid to a single non-zero tile", () => {
    render(
      <SparseHeatmap
        tiles={[{ date: "2026-04-20", xp: 12 }]}
        todayUtc={TODAY}
      />,
    );

    const tile = screen.getByTestId("heatmap-tile-2026-04-20");
    expect(tile).toBeInTheDocument();
    // 10–29 XP bucket → mid emerald saturation.
    expect(tile.className).toContain("bg-emerald-500/50");
    expect(tile).toHaveAttribute("title", "2026-04-20: 12 XP");
  });

  it("renders distinct color classes per XP bucket", () => {
    render(
      <SparseHeatmap
        tiles={[
          { date: "2026-04-21", xp: 3 }, // 1–9 → low
          { date: "2026-04-22", xp: 15 }, // 10–29 → mid
          { date: "2026-04-23", xp: 60 }, // 30+ → full
        ]}
        todayUtc={TODAY}
      />,
    );

    const low = screen.getByTestId("heatmap-tile-2026-04-21");
    const mid = screen.getByTestId("heatmap-tile-2026-04-22");
    const full = screen.getByTestId("heatmap-tile-2026-04-23");

    expect(low.className).toContain("bg-emerald-500/20");
    expect(mid.className).toContain("bg-emerald-500/50");
    // The full bucket is the bare token, no opacity suffix — guard
    // against the substring matching the partial ones above.
    expect(full.className).toMatch(/bg-emerald-500(?!\/)/);
  });

  it("places today's tile last in iteration order (rightmost-bottommost)", () => {
    const { container } = render(
      <SparseHeatmap
        tiles={[{ date: TODAY, xp: 50 }]}
        todayUtc={TODAY}
      />,
    );

    const datedCells = container.querySelectorAll("[data-xp]");
    const last = datedCells[datedCells.length - 1] as HTMLElement;
    expect(last.getAttribute("data-testid")).toBe(`heatmap-tile-${TODAY}`);
    expect(last.getAttribute("data-xp")).toBe("50");
  });
});
