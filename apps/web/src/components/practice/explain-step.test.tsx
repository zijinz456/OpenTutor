import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { ExplainStep } from "./explain-step";

const KEY = (id: string) => `learndopamine:explain:${id}`;

describe("ExplainStep", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("starts collapsed when correct=true and shows the 'Explain it' pill", () => {
    render(<ExplainStep problemId="p-correct" correct={true} />);
    expect(
      screen.getByTestId("explain-step-expand-p-correct"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("explain-step-textarea-p-correct"),
    ).not.toBeInTheDocument();
  });

  it("starts expanded and auto-focuses the textarea on miss", async () => {
    render(<ExplainStep problemId="p-miss" correct={false} />);
    const ta = await screen.findByTestId("explain-step-textarea-p-miss");
    expect(ta).toBeInTheDocument();
    await waitFor(() => {
      expect(document.activeElement).toBe(ta);
    });
  });

  it("Save click writes the textarea value to localStorage", async () => {
    render(<ExplainStep problemId="p-save" correct={false} />);
    const ta = await screen.findByTestId("explain-step-textarea-p-save");
    fireEvent.change(ta, { target: { value: "I traced the loop step by step." } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("explain-step-save-p-save"));
    });
    expect(window.localStorage.getItem(KEY("p-save"))).toBe(
      "I traced the loop step by step.",
    );
    expect(
      screen.getByTestId("explain-step-saved-p-save"),
    ).toHaveTextContent(/saved/i);
  });

  it("reads existing stored text on mount", async () => {
    window.localStorage.setItem(KEY("p-existing"), "Past me said this.");
    render(<ExplainStep problemId="p-existing" correct={false} />);
    const ta = (await screen.findByTestId(
      "explain-step-textarea-p-existing",
    )) as HTMLTextAreaElement;
    expect(ta.value).toBe("Past me said this.");
  });

  it("clicking the 'Explain it' pill expands to the textarea", async () => {
    render(<ExplainStep problemId="p-toggle" correct={true} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("explain-step-expand-p-toggle"));
    });
    expect(
      await screen.findByTestId("explain-step-textarea-p-toggle"),
    ).toBeInTheDocument();
  });
});
