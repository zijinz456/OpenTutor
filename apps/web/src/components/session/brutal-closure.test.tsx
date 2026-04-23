import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { BrutalClosure } from "./brutal-closure";

describe("<BrutalClosure>", () => {
  it("renders time, max streak, mastered count", () => {
    render(
      <BrutalClosure
        durationMs={1_320_000}
        maxStreak={14}
        masteredCount={30}
        forceRetiredCount={0}
        conceptFailTally={{}}
        onBack={() => {}}
        onRunAnother={() => {}}
      />,
    );

    expect(screen.getByTestId("brutal-closure-time")).toHaveTextContent("22:00");
    expect(screen.getByTestId("brutal-closure-streak")).toHaveTextContent(
      "Max streak: 14",
    );
    expect(screen.getByTestId("brutal-closure-mastered")).toHaveTextContent(
      "30 cards",
    );
    // 0 force-retired → no diagnostic hint surfaces.
    expect(screen.queryByTestId("brutal-closure-retired-hint")).toBeNull();
  });

  it("renders top-3 weakest concepts sorted desc by fail count", () => {
    render(
      <BrutalClosure
        durationMs={600_000}
        maxStreak={5}
        masteredCount={20}
        forceRetiredCount={2}
        conceptFailTally={{
          asyncio: 3,
          gil: 5,
          pydantic: 2,
          decorators: 1,
        }}
        onBack={() => {}}
        onRunAnother={() => {}}
      />,
    );

    const weakest = screen.getByTestId("brutal-closure-weakest");
    // Top-3 by count: gil(5), asyncio(3), pydantic(2).
    const items = within(weakest).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("gil");
    expect(items[0]).toHaveTextContent("5");
    expect(items[1]).toHaveTextContent("asyncio");
    expect(items[1]).toHaveTextContent("3");
    expect(items[2]).toHaveTextContent("pydantic");
    expect(items[2]).toHaveTextContent("2");
    // `decorators` (count=1) should be trimmed from top-3.
    expect(within(weakest).queryByText("decorators")).toBeNull();
    // Force-retire hint surfaces because the count is > 0.
    expect(screen.getByTestId("brutal-closure-retired-hint")).toHaveTextContent(
      /10-attempt cap/i,
    );
  });
});
