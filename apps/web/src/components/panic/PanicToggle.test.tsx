import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PanicToggle } from "./PanicToggle";
import { usePanicStore } from "@/store/panic";

/**
 * PanicToggle tests (Phase 14 T2).
 */

describe("<PanicToggle>", () => {
  beforeEach(() => {
    window.localStorage.clear();
    usePanicStore.setState({ enabled: false, enabledAt: null });
  });

  it("renders toggle button with data-testid", () => {
    render(<PanicToggle />);
    const btn = screen.getByTestId("panic-toggle");
    expect(btn).toBeInTheDocument();
    // aria-pressed reflects off-state initially
    expect(btn.getAttribute("aria-pressed")).toBe("false");
  });

  it("click flips the panic store state", () => {
    render(<PanicToggle />);
    const btn = screen.getByTestId("panic-toggle");

    fireEvent.click(btn);
    expect(usePanicStore.getState().enabled).toBe(true);
    expect(btn.getAttribute("aria-pressed")).toBe("true");
  });
});
