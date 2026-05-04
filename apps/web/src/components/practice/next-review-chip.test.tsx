import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NextReviewChip } from "./next-review-chip";

describe("NextReviewChip", () => {
  it("renders nothing when intervalDays is 0 (FSRS stability=0 edge case)", () => {
    const { container } = render(<NextReviewChip intervalDays={0} />);
    // Self-hide guard — see component's architect-plan note. The chip
    // must NEVER render "Returns in 0 days".
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId("next-review-chip")).not.toBeInTheDocument();
  });

  it("renders 'Returns in 2 days' when only intervalDays is provided", () => {
    render(<NextReviewChip intervalDays={2} />);
    const chip = screen.getByTestId("next-review-chip");
    expect(chip).toHaveTextContent("Returns in 2 days");
  });

  it("renders 'Returns Mon 18 May' for a near-term date (interval ≤ 7d)", () => {
    // 2026-05-18 is a Monday (UTC). intervalDays = 14 falls outside the
    // near-term threshold (7d), so we use 5 to exercise the weekday path.
    render(
      <NextReviewChip intervalDays={5} nextReviewAt="2026-05-18T00:00:00Z" />,
    );
    const chip = screen.getByTestId("next-review-chip");
    expect(chip).toHaveTextContent("Returns Mon 18 May");
  });

  it("falls back to day-count when interval is > 7d even with a date", () => {
    // 14d horizon — weekday is no longer load-bearing, day count is more
    // legible.
    render(
      <NextReviewChip intervalDays={14} nextReviewAt="2026-05-18T00:00:00Z" />,
    );
    const chip = screen.getByTestId("next-review-chip");
    expect(chip).toHaveTextContent("Returns in 14 days");
  });

  it("hides on null/undefined intervalDays (tracker failure path)", () => {
    const { container } = render(<NextReviewChip intervalDays={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("uses singular 'day' for intervalDays=1", () => {
    render(<NextReviewChip intervalDays={1} />);
    const chip = screen.getByTestId("next-review-chip");
    expect(chip).toHaveTextContent("Returns in 1 day");
    expect(chip).not.toHaveTextContent("days");
  });
});
