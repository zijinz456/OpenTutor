import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ContinueMissionHero } from "./continue-mission-hero";
import type { CurrentMission } from "@/lib/api/paths";

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
  it("shows a skeleton while mission prop is undefined", () => {
    render(
      <ContinueMissionHero mission={undefined} gate={false} dueCardCount={0} />,
    );

    expect(
      screen.getByTestId("continue-mission-hero-skeleton"),
    ).toBeInTheDocument();
  });

  it("renders the empty state when mission prop is null", () => {
    render(
      <ContinueMissionHero mission={null} gate={false} dueCardCount={0} />,
    );

    expect(
      screen.getByTestId("continue-mission-hero-empty"),
    ).toBeInTheDocument();
    expect(screen.getByText("Pick your next mission.")).toBeInTheDocument();
    expect(screen.getByTestId("continue-mission-hero-browse")).toHaveAttribute(
      "href",
      "/tracks",
    );
  });

  it("renders the in-progress mission state with the mission deep link when gate=false", () => {
    render(
      <ContinueMissionHero
        mission={makeMission()}
        gate={false}
        dueCardCount={0}
      />,
    );

    expect(screen.getByTestId("continue-mission-hero")).toBeInTheDocument();
    expect(screen.getByTestId("continue-mission-hero-title")).toHaveTextContent(
      "Loops",
    );
    expect(screen.getByText("2/5 tasks done")).toBeInTheDocument();
    expect(screen.getByText("40% through")).toBeInTheDocument();
    expect(screen.getByTestId("continue-mission-hero-open")).toHaveAttribute(
      "href",
      "/tracks/python-fundamentals/missions/room-1",
    );
    expect(screen.getByTestId("continue-mission-hero-open")).toHaveTextContent(
      "Pick up where you left off",
    );
    expect(screen.getByTestId("continue-mission-hero-track")).toHaveAttribute(
      "href",
      "/tracks/python-fundamentals",
    );
  });

  it("does not show the gate helper when gate=false", () => {
    render(
      <ContinueMissionHero
        mission={makeMission()}
        gate={false}
        dueCardCount={0}
      />,
    );

    expect(
      screen.queryByTestId("continue-mission-hero-gate"),
    ).not.toBeInTheDocument();
  });

  it("routes the primary CTA to /session/daily and shows gate helper when gate=true", () => {
    render(
      <ContinueMissionHero
        mission={makeMission()}
        gate={true}
        dueCardCount={4}
      />,
    );

    const open = screen.getByTestId("continue-mission-hero-open");
    expect(open).toHaveAttribute("href", "/session/daily");
    expect(open).toHaveTextContent("Start after review");

    const gate = screen.getByTestId("continue-mission-hero-gate");
    expect(gate).toBeInTheDocument();
    expect(gate).toHaveTextContent("Review first: 4 cards due");
  });

  it("renders why-now and outcome instructional rows from mission text", () => {
    render(
      <ContinueMissionHero
        mission={makeMission({
          intro_excerpt: "Loops are the workhorse of Python.",
          outcome: "Filter a list with a for-loop.",
        })}
        gate={false}
        dueCardCount={0}
      />,
    );

    const why = screen.getByTestId("continue-mission-hero-why-now");
    expect(why).toHaveTextContent("Why this now:");
    expect(why).toHaveTextContent("Loops are the workhorse of Python.");

    const outcome = screen.getByTestId("continue-mission-hero-outcome");
    expect(outcome).toHaveTextContent("By the end:");
    expect(outcome).toHaveTextContent("Filter a list with a for-loop.");
  });

  it("falls back to safe defaults when mission text is null", () => {
    render(
      <ContinueMissionHero
        mission={makeMission({ intro_excerpt: null, outcome: null })}
        gate={false}
        dueCardCount={0}
      />,
    );

    expect(
      screen.getByTestId("continue-mission-hero-why-now"),
    ).toHaveTextContent(
      "Picking up an in-progress mission keeps your context warm.",
    );
    expect(
      screen.getByTestId("continue-mission-hero-outcome"),
    ).toHaveTextContent(
      "You can apply this skill on a fresh task without help.",
    );
  });
});
