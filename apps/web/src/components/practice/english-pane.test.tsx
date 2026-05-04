import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EnglishPane } from "./english-pane";

describe("EnglishPane", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders a textarea + voice button + submit (Slice 3 item #2 shape)", () => {
    render(<EnglishPane problemId="e1" question="Describe your last week." />);

    expect(screen.getByTestId("english-pane-textarea-e1")).toBeInTheDocument();
    expect(screen.getByTestId("english-pane-voice-e1")).toBeInTheDocument();
    expect(screen.getByTestId("practice-shell-submit-e1")).toBeInTheDocument();
  });

  it("disables submit while the textarea is empty (or whitespace)", () => {
    render(<EnglishPane problemId="e2" question="Q" />);
    const submit = screen.getByTestId("practice-shell-submit-e2");
    expect(submit).toBeDisabled();

    const textarea = screen.getByTestId(
      "english-pane-textarea-e2",
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "   " } });
    expect(submit).toBeDisabled();

    fireEvent.change(textarea, { target: { value: "I went to the park." } });
    expect(submit).not.toBeDisabled();
  });

  it("fires onSubmit with the textarea value", () => {
    const handleSubmit = vi.fn();
    render(
      <EnglishPane problemId="e3" question="Q" onSubmit={handleSubmit} />,
    );
    const textarea = screen.getByTestId(
      "english-pane-textarea-e3",
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "my answer" } });
    fireEvent.click(screen.getByTestId("practice-shell-submit-e3"));
    expect(handleSubmit).toHaveBeenCalledWith("my answer");
  });

  it("toggles voice button aria-pressed state on click", () => {
    render(<EnglishPane problemId="e4" question="Q" />);
    const voice = screen.getByTestId("english-pane-voice-e4");
    expect(voice).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(voice);
    expect(voice).toHaveAttribute("aria-pressed", "true");
  });
});
