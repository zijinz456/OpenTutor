import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { TodayPlanCard } from "./today-plan-card";
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

describe("<TodayPlanCard>", () => {
  it("renders the 3 ordered step testids in document order", () => {
    render(
      <TodayPlanCard totalDueFlashcards={3} mission={makeMission()} />,
    );

    const card = screen.getByTestId("today-plan-card");
    expect(card).toBeInTheDocument();

    const review = screen.getByTestId("today-plan-step-review");
    const mission = screen.getByTestId("today-plan-step-mission");
    const recap = screen.getByTestId("today-plan-step-recap");

    // All three live inside the same card.
    expect(card).toContainElement(review);
    expect(card).toContainElement(mission);
    expect(card).toContainElement(recap);

    // Document order: review → mission → recap.
    const order = review.compareDocumentPosition(mission);
    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const order2 = mission.compareDocumentPosition(recap);
    expect(order2 & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("step 1 shows due cards count when totalDueFlashcards > 0", () => {
    render(
      <TodayPlanCard totalDueFlashcards={7} mission={makeMission()} />,
    );

    const review = screen.getByTestId("today-plan-step-review");
    expect(review).toHaveTextContent("Review first");
    expect(review).toHaveTextContent("7 cards due");
  });

  it("step 1 shows the review-clear state when no cards are due", () => {
    render(
      <TodayPlanCard totalDueFlashcards={0} mission={makeMission()} />,
    );

    const review = screen.getByTestId("today-plan-step-review");
    expect(review).toHaveTextContent("Review clear");
    expect(review).toHaveTextContent("Nothing due. Ready for new ground.");
  });

  it("step 2 shows the mission title and progress when a mission exists", () => {
    render(
      <TodayPlanCard
        totalDueFlashcards={0}
        mission={makeMission({
          title: "Loops",
          task_complete: 2,
          task_total: 5,
          eta_minutes: 20,
        })}
      />,
    );

    const missionStep = screen.getByTestId("today-plan-step-mission");
    expect(missionStep).toHaveTextContent("Mission: Loops");
    expect(missionStep).toHaveTextContent("2/5 tasks");
    expect(missionStep).toHaveTextContent("20 min");
  });

  it("step 2 falls back to 'Pick a track' when mission is null", () => {
    render(<TodayPlanCard totalDueFlashcards={0} mission={null} />);

    const missionStep = screen.getByTestId("today-plan-step-mission");
    expect(missionStep).toHaveTextContent("Pick a track");
    expect(missionStep).toHaveTextContent("Browse tracks to start one.");
  });
});
