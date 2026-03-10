import { describe, it, expect } from "vitest";
import { useRef } from "react";
import { render, screen } from "@/test-utils";
import { useFocusTrap } from "./use-focus-trap";

function TrapHarness({ active }: { active: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, active);
  return (
    <div ref={ref} tabIndex={-1} data-testid="container">
      <button data-testid="btn-1">First</button>
      <button data-testid="btn-2">Second</button>
      <button data-testid="btn-3">Third</button>
    </div>
  );
}

describe("useFocusTrap", () => {
  it("moves focus to first focusable element when activated", () => {
    render(<TrapHarness active={true} />);
    expect(document.activeElement).toBe(screen.getByTestId("btn-1"));
  });

  it("does not move focus when inactive", () => {
    render(<TrapHarness active={false} />);
    expect(document.activeElement).not.toBe(screen.getByTestId("btn-1"));
  });

  it("wraps focus forward on Tab at last element", async () => {
    const { user } = render(<TrapHarness active={true} />);
    // Focus is on btn-1, tab to btn-2, tab to btn-3
    await user.tab();
    expect(document.activeElement).toBe(screen.getByTestId("btn-2"));
    await user.tab();
    expect(document.activeElement).toBe(screen.getByTestId("btn-3"));
    // Tab again should wrap to btn-1
    await user.tab();
    expect(document.activeElement).toBe(screen.getByTestId("btn-1"));
  });

  it("wraps focus backward on Shift+Tab at first element", async () => {
    const { user } = render(<TrapHarness active={true} />);
    // Focus starts on btn-1, Shift+Tab should go to btn-3
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(screen.getByTestId("btn-3"));
  });
});
