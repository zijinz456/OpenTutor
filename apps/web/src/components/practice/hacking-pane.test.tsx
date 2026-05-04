import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { HackingPane } from "./hacking-pane";

describe("HackingPane", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders a Juice Shop iframe + proof input + submit (Slice 3 item #3 shape)", () => {
    render(<HackingPane problemId="h1" question="Capture the admin token." />);

    const iframe = screen.getByTestId("hacking-pane-iframe-h1");
    expect(iframe).toBeInTheDocument();
    expect(iframe.tagName).toBe("IFRAME");
    expect(iframe).toHaveAttribute("src", "http://localhost:3000");
    // Sandbox contract per Phase 12 — must restrict scripts but allow
    // forms/scripts so the training app actually loads.
    expect(iframe).toHaveAttribute(
      "sandbox",
      "allow-scripts allow-same-origin allow-forms",
    );

    expect(screen.getByTestId("hacking-pane-proof-h1")).toBeInTheDocument();
    expect(screen.getByTestId("practice-shell-submit-h1")).toBeInTheDocument();
  });

  it("uses a custom juiceShopUrl when provided", () => {
    render(
      <HackingPane
        problemId="h2"
        question="Q"
        juiceShopUrl="http://localhost:42420/#/score-board"
      />,
    );
    expect(screen.getByTestId("hacking-pane-iframe-h2")).toHaveAttribute(
      "src",
      "http://localhost:42420/#/score-board",
    );
  });

  it("disables submit while the proof input is empty", () => {
    render(<HackingPane problemId="h3" question="Q" />);
    const submit = screen.getByTestId("practice-shell-submit-h3");
    expect(submit).toBeDisabled();

    const proof = screen.getByTestId(
      "hacking-pane-proof-h3",
    ) as HTMLInputElement;
    fireEvent.change(proof, { target: { value: "{flag:abc}" } });
    expect(submit).not.toBeDisabled();
  });

  it("fires onSubmit with the proof value", () => {
    const handleSubmit = vi.fn();
    render(
      <HackingPane problemId="h4" question="Q" onSubmit={handleSubmit} />,
    );
    fireEvent.change(screen.getByTestId("hacking-pane-proof-h4"), {
      target: { value: "captured-flag-001" },
    });
    fireEvent.click(screen.getByTestId("practice-shell-submit-h4"));
    expect(handleSubmit).toHaveBeenCalledWith("captured-flag-001");
  });
});
