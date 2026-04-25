import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { GamificationWidget } from "./gamification-widget";
import type { GamificationDashboard } from "@/lib/api/gamification";

const getGamificationDashboardMock = vi.fn();
vi.mock("@/lib/api/gamification", async () => ({
  getGamificationDashboard: (...args: unknown[]) =>
    getGamificationDashboardMock(...args),
}));

// Stub the sub-components so this test focuses on widget orchestration.
// Sub-component contracts are exercised by their own test files.
vi.mock("./xp-level-chip", () => ({
  XpLevelChip: (props: { xpTotal: number; levelTier: string }) => (
    <div
      data-testid="xp-level-chip"
      data-xp={props.xpTotal}
      data-tier={props.levelTier}
    />
  ),
}));

vi.mock("./streak-chip", () => ({
  StreakChip: (props: { streakDays: number; freezesLeft: number }) => (
    <div
      data-testid="streak-chip"
      data-days={props.streakDays}
      data-freezes={props.freezesLeft}
    />
  ),
}));

vi.mock("./sparse-heatmap", () => ({
  SparseHeatmap: (props: { tiles: { date: string; xp: number }[] }) => (
    <div data-testid="sparse-heatmap" data-tiles={props.tiles.length} />
  ),
}));

function makeDashboard(
  overrides: Partial<GamificationDashboard> = {},
): GamificationDashboard {
  return {
    xp_total: 1200,
    level_tier: "Silver II",
    level_name: "Silver",
    level_progress_pct: 40,
    // Phase 16c Bundle B — required field added to the type by Subagent B.
    xp_to_next_level: 300,
    streak_days: 5,
    streak_freezes_left: 2,
    daily_goal_xp: 30,
    daily_xp_earned: 12,
    heatmap: [{ date: "2026-04-25", xp: 12 }],
    active_paths: [],
    ...overrides,
  };
}

describe("<GamificationWidget>", () => {
  beforeEach(() => {
    getGamificationDashboardMock.mockReset();
  });

  it("shows the loading skeleton on mount", () => {
    // Pending promise — widget stays in loading state.
    getGamificationDashboardMock.mockImplementation(
      () => new Promise(() => {}),
    );
    render(<GamificationWidget />);

    expect(
      screen.getByTestId("gamification-widget-loading"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("gamification-widget-content"),
    ).not.toBeInTheDocument();
  });

  it("renders all 3 sub-components once data resolves", async () => {
    getGamificationDashboardMock.mockResolvedValue(makeDashboard());
    render(<GamificationWidget />);

    await waitFor(() => {
      expect(
        screen.getByTestId("gamification-widget-content"),
      ).toBeInTheDocument();
    });

    expect(screen.getByTestId("xp-level-chip")).toBeInTheDocument();
    expect(screen.getByTestId("streak-chip")).toBeInTheDocument();
    expect(screen.getByTestId("sparse-heatmap")).toBeInTheDocument();
    expect(screen.getByTestId("xp-level-chip")).toHaveAttribute(
      "data-xp",
      "1200",
    );
    expect(screen.getByTestId("streak-chip")).toHaveAttribute(
      "data-days",
      "5",
    );
    expect(screen.getByTestId("sparse-heatmap")).toHaveAttribute(
      "data-tiles",
      "1",
    );
  });

  it("shows error message + retry button when the API rejects", async () => {
    getGamificationDashboardMock.mockRejectedValue({
      status: 500,
      message: "boom",
    });
    render(<GamificationWidget />);

    await waitFor(() => {
      expect(
        screen.getByTestId("gamification-widget-error"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("gamification-widget-error"),
    ).toHaveTextContent("Couldn't load progress");
    expect(
      screen.getByTestId("gamification-widget-retry"),
    ).toBeInTheDocument();
  });

  it("re-fetches when the retry button is clicked", async () => {
    getGamificationDashboardMock
      .mockRejectedValueOnce({ status: 500, message: "boom" })
      .mockResolvedValueOnce(makeDashboard({ xp_total: 99 }));
    render(<GamificationWidget />);

    await waitFor(() => {
      expect(
        screen.getByTestId("gamification-widget-error"),
      ).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("gamification-widget-retry"));

    await waitFor(() => {
      expect(
        screen.getByTestId("gamification-widget-content"),
      ).toBeInTheDocument();
    });
    expect(getGamificationDashboardMock).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("xp-level-chip")).toHaveAttribute(
      "data-xp",
      "99",
    );
  });

  it("renders without crashing for a brand-new account (zeros + empty arrays)", async () => {
    getGamificationDashboardMock.mockResolvedValue(
      makeDashboard({
        xp_total: 0,
        level_tier: "Bronze I",
        level_name: "Bronze",
        level_progress_pct: 0,
        streak_days: 0,
        streak_freezes_left: 0,
        daily_goal_xp: 0,
        daily_xp_earned: 0,
        heatmap: [],
        active_paths: [],
      }),
    );
    render(<GamificationWidget />);

    await waitFor(() => {
      expect(
        screen.getByTestId("gamification-widget-content"),
      ).toBeInTheDocument();
    });
    expect(screen.getByTestId("sparse-heatmap")).toHaveAttribute(
      "data-tiles",
      "0",
    );
  });
});
