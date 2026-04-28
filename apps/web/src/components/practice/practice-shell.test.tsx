import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PracticeShell } from "./practice-shell";

describe("PracticeShell", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders the variant caption + question + surface slot", () => {
    render(
      <PracticeShell
        problemId="p1"
        variant="python"
        question="Write a list comprehension that doubles each item."
        surface={<div data-testid="custom-surface">surface body</div>}
        correct={false}
        onSubmit={() => undefined}
      />,
    );

    expect(screen.getByTestId("practice-shell-p1")).toBeInTheDocument();
    expect(screen.getByTestId("practice-shell-caption-p1")).toHaveTextContent(
      "Python · Practice",
    );
    expect(screen.getByTestId("practice-shell-question-p1")).toHaveTextContent(
      "Write a list comprehension that doubles each item.",
    );
    expect(screen.getByTestId("custom-surface")).toBeInTheDocument();
  });

  it("renders the optional output slot only when provided", () => {
    const { rerender } = render(
      <PracticeShell
        problemId="p2"
        variant="english"
        question="Describe yourself in one sentence."
        surface={<div />}
        correct={false}
        onSubmit={() => undefined}
      />,
    );
    expect(screen.queryByTestId("practice-shell-output-p2")).toBeNull();

    rerender(
      <PracticeShell
        problemId="p2"
        variant="english"
        question="Describe yourself in one sentence."
        surface={<div />}
        output={<div data-testid="run-output">verdict goes here</div>}
        correct={false}
        onSubmit={() => undefined}
      />,
    );
    expect(screen.getByTestId("practice-shell-output-p2")).toBeInTheDocument();
    expect(screen.getByTestId("run-output")).toBeInTheDocument();
  });

  it("always mounts the explain rail (mandatory across variants)", () => {
    render(
      <PracticeShell
        problemId="p3"
        variant="hacking"
        question="Capture the admin token."
        surface={<div />}
        correct={false}
        onSubmit={() => undefined}
      />,
    );
    // ExplainStep on miss starts expanded — textarea should be in the DOM.
    expect(screen.getByTestId("explain-step-textarea-p3")).toBeInTheDocument();
  });

  it("fires onSubmit when the primary CTA is clicked", () => {
    const handleSubmit = vi.fn();
    render(
      <PracticeShell
        problemId="p4"
        variant="python"
        question="Run the tests."
        surface={<div />}
        correct={true}
        onSubmit={handleSubmit}
        submitLabel="Run tests"
      />,
    );
    const submit = screen.getByTestId("practice-shell-submit-p4");
    expect(submit).toHaveTextContent("Run tests");
    fireEvent.click(submit);
    expect(handleSubmit).toHaveBeenCalledTimes(1);
  });

  it("disables submit when submitDisabled is true", () => {
    const handleSubmit = vi.fn();
    render(
      <PracticeShell
        problemId="p5"
        variant="english"
        question="Type something."
        surface={<div />}
        correct={false}
        onSubmit={handleSubmit}
        submitDisabled
      />,
    );
    const submit = screen.getByTestId("practice-shell-submit-p5");
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(handleSubmit).not.toHaveBeenCalled();
  });

  it("shows the Next-task CTA only when canAdvance is true and onAdvance is set", () => {
    // Phase B mission-progression fix. When the host hasn't latched
    // an attempt yet, the affordance is hidden so the user is not
    // tempted to skip past unread questions.
    const handleAdvance = vi.fn();
    const { rerender } = render(
      <PracticeShell
        problemId="adv1"
        variant="python"
        question="Q"
        surface={<div />}
        correct={false}
        onSubmit={() => undefined}
        onAdvance={handleAdvance}
        canAdvance={false}
      />,
    );
    expect(screen.queryByTestId("practice-shell-advance-adv1")).toBeNull();

    rerender(
      <PracticeShell
        problemId="adv1"
        variant="python"
        question="Q"
        surface={<div />}
        correct={false}
        onSubmit={() => undefined}
        onAdvance={handleAdvance}
        canAdvance={true}
      />,
    );
    const advanceBtn = screen.getByTestId("practice-shell-advance-adv1");
    expect(advanceBtn).toHaveTextContent("Next task");
    fireEvent.click(advanceBtn);
    expect(handleAdvance).toHaveBeenCalledTimes(1);
  });

  it("hides the Next-task CTA when onAdvance is omitted (last task in mission)", () => {
    render(
      <PracticeShell
        problemId="adv2"
        variant="python"
        question="Q"
        surface={<div />}
        correct={true}
        onSubmit={() => undefined}
        canAdvance={true}
      />,
    );
    expect(screen.queryByTestId("practice-shell-advance-adv2")).toBeNull();
  });

  it("colors the caption per variant accent (data-variant attribute)", () => {
    const { rerender } = render(
      <PracticeShell
        problemId="p6"
        variant="python"
        question="Q"
        surface={<div />}
        correct={false}
        onSubmit={() => undefined}
      />,
    );
    expect(screen.getByTestId("practice-shell-p6")).toHaveAttribute(
      "data-variant",
      "python",
    );

    rerender(
      <PracticeShell
        problemId="p6"
        variant="english"
        question="Q"
        surface={<div />}
        correct={false}
        onSubmit={() => undefined}
      />,
    );
    expect(screen.getByTestId("practice-shell-p6")).toHaveAttribute(
      "data-variant",
      "english",
    );
    expect(screen.getByTestId("practice-shell-caption-p6")).toHaveTextContent(
      "English · Practice",
    );

    rerender(
      <PracticeShell
        problemId="p6"
        variant="hacking"
        question="Q"
        surface={<div />}
        correct={false}
        onSubmit={() => undefined}
      />,
    );
    expect(screen.getByTestId("practice-shell-p6")).toHaveAttribute(
      "data-variant",
      "hacking",
    );
    expect(screen.getByTestId("practice-shell-caption-p6")).toHaveTextContent(
      "Hacking · Practice",
    );
  });
});
