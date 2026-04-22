import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SessionClosure } from "./session-closure";

describe("<SessionClosure>", () => {
  it("shows the no-guilt headline and subtext", () => {
    render(<SessionClosure correct={0} total={0} onBack={() => {}} />);
    expect(screen.getByText(/done for today/i)).toBeInTheDocument();
    expect(screen.getByText(/come back when you want/i)).toBeInTheDocument();
  });

  it("contains no streak, keep-going, or progress-bar language", () => {
    const { container } = render(
      <SessionClosure correct={4} total={5} onBack={() => {}} />,
    );
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/streak/i);
    expect(text).not.toMatch(/keep going/i);
    expect(text).not.toMatch(/keep it up/i);
    expect(text).not.toMatch(/only done/i);
    expect(text).not.toMatch(/behind/i);
    expect(text).not.toMatch(/overdue/i);
    expect(text).not.toMatch(/tomorrow/i);
    expect(container.querySelector('[role="progressbar"]')).toBeNull();
  });

  it("formats the singular stat correctly", () => {
    render(<SessionClosure correct={1} total={1} onBack={() => {}} />);
    expect(screen.getByTestId("session-closure-stats")).toHaveTextContent(
      "1 card reviewed · 1 remembered",
    );
  });

  it("formats the plural stat correctly", () => {
    render(<SessionClosure correct={4} total={5} onBack={() => {}} />);
    expect(screen.getByTestId("session-closure-stats")).toHaveTextContent(
      "5 cards reviewed · 4 remembered",
    );
  });

  it("routes home on primary button click", async () => {
    const onBack = vi.fn();
    const user = userEvent.setup();
    render(<SessionClosure correct={3} total={5} onBack={onBack} />);
    await user.click(screen.getByTestId("session-closure-back"));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it("hides 'Do 1 more?' when onDoOneMore is not provided", () => {
    render(<SessionClosure correct={5} total={5} onBack={() => {}} />);
    expect(screen.queryByTestId("session-closure-one-more")).toBeNull();
  });

  it("fires onDoOneMore when the secondary action is clicked", async () => {
    const onDoOneMore = vi.fn();
    const user = userEvent.setup();
    render(
      <SessionClosure
        correct={5}
        total={5}
        onBack={() => {}}
        onDoOneMore={onDoOneMore}
      />,
    );
    await user.click(screen.getByTestId("session-closure-one-more"));
    expect(onDoOneMore).toHaveBeenCalledOnce();
  });
});
