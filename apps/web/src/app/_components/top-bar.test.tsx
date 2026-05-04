import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { TopBar } from "./top-bar";
import type { GamificationDashboard } from "@/lib/api/gamification";

const getGamificationDashboardMock = vi.fn();
vi.mock("@/lib/api/gamification", () => ({
  getGamificationDashboard: (...args: unknown[]) =>
    getGamificationDashboardMock(...args),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/tracks",
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  } & React.HTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/shared/today-tools-popover", () => ({
  TodayToolsPopover: () => (
    <button type="button" data-testid="today-tools-trigger">
      Today tools
    </button>
  ),
}));

function makeDashboard(
  overrides: Partial<GamificationDashboard> = {},
): GamificationDashboard {
  return {
    xp_total: 0,
    level_tier: "Bronze I",
    level_name: "Bronze",
    level_progress_pct: 0,
    xp_to_next_level: 100,
    streak_days: 2,
    streak_freezes_left: 0,
    daily_goal_xp: 0,
    daily_xp_earned: 0,
    heatmap: [],
    active_paths: [],
    ...overrides,
  };
}

describe("<TopBar>", () => {
  beforeEach(() => {
    getGamificationDashboardMock.mockReset();
  });

  it("renders nav links and today-tools trigger", async () => {
    getGamificationDashboardMock.mockResolvedValue(makeDashboard());
    render(<TopBar />);

    expect(screen.getByTestId("top-bar-link-tracks")).toHaveAttribute(
      "href",
      "/tracks",
    );
    expect(screen.getByTestId("top-bar-link-review")).toHaveAttribute(
      "href",
      "/session/daily",
    );
    expect(screen.getByTestId("top-bar-link-recap")).toHaveAttribute(
      "href",
      "/recap",
    );
    expect(screen.getByTestId("today-tools-trigger")).toBeInTheDocument();
  });

  it("renders the live streak value once /api/gamification/dashboard resolves", async () => {
    getGamificationDashboardMock.mockResolvedValue(
      makeDashboard({ streak_days: 2 }),
    );
    render(<TopBar />);

    await waitFor(() => {
      expect(screen.getByTestId("top-bar-streak-chip")).toHaveAttribute(
        "data-streak-status",
        "loaded",
      );
    });
    expect(screen.getByTestId("top-bar-streak-chip")).toHaveTextContent("🔥 2");
  });

  it("renders streak_days=0 honestly (no streak yet is a legit state)", async () => {
    getGamificationDashboardMock.mockResolvedValue(
      makeDashboard({ streak_days: 0 }),
    );
    render(<TopBar />);

    await waitFor(() => {
      expect(screen.getByTestId("top-bar-streak-chip")).toHaveAttribute(
        "data-streak-status",
        "loaded",
      );
    });
    expect(screen.getByTestId("top-bar-streak-chip")).toHaveTextContent("🔥 0");
  });

  it("renders an em-dash placeholder while the API call is pending", () => {
    // Pending promise — chip stays in loading state, NOT "🔥 0" (which
    // would mislead users into thinking they lost their streak).
    getGamificationDashboardMock.mockImplementation(
      () => new Promise(() => {}),
    );
    render(<TopBar />);

    const chip = screen.getByTestId("top-bar-streak-chip");
    expect(chip).toHaveAttribute("data-streak-status", "loading");
    expect(chip).toHaveAttribute("aria-busy", "true");
    expect(chip).toHaveTextContent("🔥 —");
  });

  it("falls back to placeholder on API error without crashing", async () => {
    getGamificationDashboardMock.mockRejectedValue({
      status: 500,
      message: "boom",
    });
    render(<TopBar />);

    await waitFor(() => {
      expect(screen.getByTestId("top-bar-streak-chip")).toHaveAttribute(
        "data-streak-status",
        "error",
      );
    });
    expect(screen.getByTestId("top-bar-streak-chip")).toHaveTextContent(
      "🔥 —",
    );
  });
});
