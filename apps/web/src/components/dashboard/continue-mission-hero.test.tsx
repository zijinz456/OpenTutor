import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ContinueMissionHero } from "./continue-mission-hero";
import type { CurrentMission } from "@/lib/api/paths";

const getCurrentMissionMock = vi.fn();

vi.mock("@/lib/api/paths", async () => ({
  getCurrentMission: (...args: unknown[]) => getCurrentMissionMock(...args),
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

function makeMission(overrides: Partial<CurrentMission> = {}): CurrentMission {
  return {
    mission_id: "room-1",
    path_id: "path-1",
    path_slug: "python-fundamentals",
    path_title: "Python Fundamentals",
    title: "Loops",
    intro_excerpt: "Start with loops.",
    outcome: "Write a loop that filters a list",
    difficulty: 3,
    eta_minutes: 20,
    module_label: "Basics",
    task_total: 5,
    task_complete: 2,
    progress_pct: 40,
    ...overrides,
  };
}

describe("<ContinueMissionHero>", () => {
  beforeEach(() => {
    getCurrentMissionMock.mockReset();
  });

  it("shows a skeleton while the request is in flight", () => {
    getCurrentMissionMock.mockReturnValue(new Promise(() => undefined));
    render(<ContinueMissionHero />);

    expect(
      screen.getByTestId("continue-mission-hero-skeleton"),
    ).toBeInTheDocument();
  });

  it("renders the empty state when there is no mission in progress", async () => {
    getCurrentMissionMock.mockResolvedValue(null);
    render(<ContinueMissionHero />);

    await waitFor(() => {
      expect(
        screen.getByTestId("continue-mission-hero-empty"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("Pick your next mission.")).toBeInTheDocument();
    expect(screen.getByTestId("continue-mission-hero-browse")).toHaveAttribute(
      "href",
      "/tracks",
    );
  });

  it("renders the in-progress mission state with deep links", async () => {
    getCurrentMissionMock.mockResolvedValue(makeMission());
    render(<ContinueMissionHero />);

    await waitFor(() => {
      expect(screen.getByTestId("continue-mission-hero")).toBeInTheDocument();
    });
    expect(screen.getByTestId("continue-mission-hero-title")).toHaveTextContent(
      "Loops",
    );
    expect(screen.getByText("2/5 tasks done")).toBeInTheDocument();
    expect(screen.getByText("40% through")).toBeInTheDocument();
    expect(screen.getByTestId("continue-mission-hero-open")).toHaveAttribute(
      "href",
      "/tracks/python-fundamentals/missions/room-1",
    );
    expect(screen.getByTestId("continue-mission-hero-track")).toHaveAttribute(
      "href",
      "/tracks/python-fundamentals",
    );
  });
});
