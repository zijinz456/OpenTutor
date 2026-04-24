import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AddToReviewLink } from "./add-to-review-link";

describe("AddToReviewLink", () => {
  it("renders an anchor pointing at /wrong-answers/{course}?problem={id}", () => {
    render(<AddToReviewLink courseId="hacking-foundations" problemId="prob-42" />);
    const link = screen.getByTestId("add-to-review-link-prob-42") as HTMLAnchorElement;
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe(
      "/wrong-answers/hacking-foundations?problem=prob-42",
    );
    expect(link).toHaveTextContent(/add to review/i);
  });

  it("is a focusable element (keyboard accessible)", () => {
    render(<AddToReviewLink courseId="python-basics" problemId="abc" />);
    const link = screen.getByTestId("add-to-review-link-abc");
    // Anchors with href are tab-stops by default; assert no negative tabindex.
    expect(link.getAttribute("tabindex")).not.toBe("-1");
    link.focus();
    expect(document.activeElement).toBe(link);
  });
});
