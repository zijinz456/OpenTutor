import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PanicOverlay } from "./PanicOverlay";
import { usePanicStore } from "@/store/panic";

/**
 * PanicOverlay tests (Phase 14 T2).
 *
 * We drive the Zustand store directly (`.setState` / `.getState`) rather
 * than click through `<PanicToggle>` so we can isolate the overlay
 * behaviour from the toggle.
 */

describe("<PanicOverlay>", () => {
  beforeEach(() => {
    window.localStorage.clear();
    usePanicStore.setState({ enabled: false, enabledAt: null });
  });

  afterEach(() => {
    // Clean up body class in case a test left panic enabled.
    document.body.classList.remove("panic-mode-active");
    vi.restoreAllMocks();
  });

  it("adds panic-mode-active class to <body> when enabled", () => {
    usePanicStore.setState({ enabled: true, enabledAt: Date.now() });
    render(
      <PanicOverlay>
        <div>child</div>
      </PanicOverlay>,
    );
    expect(document.body.classList.contains("panic-mode-active")).toBe(true);
  });

  it("Escape key disables panic mode", () => {
    usePanicStore.setState({ enabled: true, enabledAt: Date.now() });
    render(
      <PanicOverlay>
        <div>child</div>
      </PanicOverlay>,
    );
    expect(usePanicStore.getState().enabled).toBe(true);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(usePanicStore.getState().enabled).toBe(false);
  });

  it("renders exit CTA when enabled", () => {
    usePanicStore.setState({ enabled: true, enabledAt: Date.now() });
    render(
      <PanicOverlay>
        <div>child</div>
      </PanicOverlay>,
    );
    expect(screen.getByTestId("panic-exit-cta")).toBeInTheDocument();
  });
});
