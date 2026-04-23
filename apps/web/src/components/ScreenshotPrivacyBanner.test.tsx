/**
 * Unit tests for <ScreenshotPrivacyBanner> (Phase 4 T6).
 *
 * The component is pure / stateless except for an internal "dismissed"
 * flag toggled by the close button. We cover:
 *   1. Warning text + testid always render.
 *   2. Default (non-dismissible) mode omits the close button.
 *   3. Dismissible mode shows the close button and — on click — calls
 *      ``onDismiss`` once and unmounts the banner (returns ``null``).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ScreenshotPrivacyBanner } from "./ScreenshotPrivacyBanner";

describe("ScreenshotPrivacyBanner", () => {
  it("renders warning text with testid", () => {
    render(<ScreenshotPrivacyBanner />);
    const banner = screen.getByTestId("screenshot-privacy-banner");
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toContain("Don't capture credentials");
  });

  it("non-dismissible by default", () => {
    render(<ScreenshotPrivacyBanner />);
    // Banner is still there, but no dismiss button should be rendered.
    expect(screen.getByTestId("screenshot-privacy-banner")).toBeInTheDocument();
    expect(
      screen.queryByTestId("screenshot-privacy-banner-dismiss"),
    ).not.toBeInTheDocument();
  });

  it("dismissible mode shows close button and calls onDismiss", () => {
    const onDismiss = vi.fn();
    render(<ScreenshotPrivacyBanner dismissible onDismiss={onDismiss} />);

    const closeBtn = screen.getByTestId("screenshot-privacy-banner-dismiss");
    expect(closeBtn).toBeInTheDocument();

    fireEvent.click(closeBtn);

    expect(onDismiss).toHaveBeenCalledTimes(1);
    // Banner unmounts / returns null after dismiss.
    expect(
      screen.queryByTestId("screenshot-privacy-banner"),
    ).not.toBeInTheDocument();
  });
});
