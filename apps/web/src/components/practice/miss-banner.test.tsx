import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MissBanner } from "./miss-banner";

describe("MissBanner", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders the canonical 'Miss. Answer: {x}' copy with the revealed answer", () => {
    render(
      <MissBanner
        problemId="p1"
        courseId="python-basics"
        revealedAnswer="42"
      />,
    );
    const copy = screen.getByTestId("miss-banner-copy-p1");
    expect(copy).toHaveTextContent("Miss. Answer: 42");
  });

  it("renders children content slot underneath the banner copy", () => {
    render(
      <MissBanner problemId="p2" courseId="python-basics" revealedAnswer="x">
        <p data-testid="custom-child">expected diff goes here</p>
      </MissBanner>,
    );
    expect(screen.getByTestId("custom-child")).toBeInTheDocument();
    expect(screen.getByTestId("miss-banner-copy-p2")).toHaveTextContent(
      "Miss. Answer: x",
    );
  });

  it("wires both the AddToReviewLink and the ExplainStep widgets", () => {
    render(
      <MissBanner
        problemId="p3"
        courseId="python-basics"
        revealedAnswer="answer-text"
      />,
    );
    expect(screen.getByTestId("add-to-review-link-p3")).toBeInTheDocument();
    // ExplainStep on miss starts expanded so the textarea renders inline.
    expect(
      screen.getByTestId("explain-step-textarea-p3"),
    ).toBeInTheDocument();
  });
});
