/**
 * Unit tests for <RubricPanel> (Phase 5 T6d).
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RubricPanel } from "./RubricPanel";
import type { RubricScores } from "@/lib/api/interview";

const behavioral: RubricScores = {
  dimensions: {
    Situation: { score: 4, feedback: "Context is clear." },
    Task: { score: 3, feedback: "Objective ok." },
    Action: { score: 5, feedback: "Strong step-by-step." },
    Result: { score: 2, feedback: "Missing quantified outcome." },
  },
  feedback_short: "Tighten the result metric — everything else solid.",
};

describe("RubricPanel", () => {
  it("renders all 4 STAR dimensions with scores and feedback", () => {
    render(<RubricPanel rubric={behavioral} turnNumber={3} />);

    const panel = screen.getByTestId("rubric-panel");
    expect(panel.getAttribute("data-turn-number")).toBe("3");
    expect(panel.textContent).toContain("Turn 3 rubric");

    for (const dim of ["Situation", "Task", "Action", "Result"]) {
      expect(screen.getByTestId(`rubric-dim-${dim}`)).toBeInTheDocument();
    }

    expect(screen.getByTestId("rubric-dim-Situation-score").textContent).toBe(
      "4 / 5",
    );
    expect(screen.getByTestId("rubric-dim-Action-score").textContent).toBe(
      "5 / 5",
    );
    expect(screen.getByTestId("rubric-dim-Result-score").textContent).toBe(
      "2 / 5",
    );
    expect(
      screen.getByTestId("rubric-dim-Action-feedback").textContent,
    ).toContain("Strong step-by-step");
    expect(screen.getByTestId("rubric-feedback-short").textContent).toContain(
      "Tighten the result metric",
    );
  });

  it("applies tiered colour classes + bar widths for extreme scores", () => {
    const extreme: RubricScores = {
      dimensions: {
        Correctness: { score: 1, feedback: "Off-base." },
        Depth: { score: 3, feedback: "Surface." },
        Tradeoff: { score: 5, feedback: "Nailed it." },
        Clarity: { score: 4, feedback: "Clean." },
      },
      feedback_short: "",
    };
    render(<RubricPanel rubric={extreme} turnNumber={1} />);

    // Score 1 → red bar, 20% width.
    const weakBar = screen.getByTestId("rubric-dim-Correctness-bar");
    expect(weakBar.className).toContain("bg-red-500");
    expect((weakBar as HTMLElement).style.width).toBe("20%");

    // Score 3 → amber bar, 60% width.
    const midBar = screen.getByTestId("rubric-dim-Depth-bar");
    expect(midBar.className).toContain("bg-amber-500");
    expect((midBar as HTMLElement).style.width).toBe("60%");

    // Score 5 → emerald bar, 100% width.
    const strongBar = screen.getByTestId("rubric-dim-Tradeoff-bar");
    expect(strongBar.className).toContain("bg-emerald-500");
    expect((strongBar as HTMLElement).style.width).toBe("100%");

    // Empty feedback_short shouldn't render the summary block.
    expect(screen.queryByTestId("rubric-feedback-short")).not.toBeInTheDocument();
  });
});
