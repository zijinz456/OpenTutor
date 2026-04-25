import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GenerateRoomCTA } from "./generate-room-cta";

// Stub the modal so we test the CTA in isolation. We assert the modal
// receives `isOpen` correctly via a data-state attribute.
vi.mock("./generate-room-modal", () => ({
  GenerateRoomModal: ({
    isOpen,
    onClose,
  }: {
    isOpen: boolean;
    onClose: () => void;
  }) =>
    isOpen ? (
      <div data-testid="generate-room-modal">
        <button
          type="button"
          data-testid="generate-room-modal-close-stub"
          onClick={onClose}
        >
          close
        </button>
      </div>
    ) : null,
}));

beforeEach(() => {
  // No-op — kept for parity with other tests that share state.
});

describe("<GenerateRoomCTA>", () => {
  it("opens the modal on click (default dashboard-rail variant)", async () => {
    const user = userEvent.setup();
    render(
      <GenerateRoomCTA
        pathId="path-1"
        courseId="course-1"
        pathSlug="python-bootcamp"
      />,
    );

    expect(
      screen.queryByTestId("generate-room-modal"),
    ).not.toBeInTheDocument();
    await user.click(screen.getByTestId("generate-room-cta-dashboard-rail"));
    expect(screen.getByTestId("generate-room-modal")).toBeInTheDocument();
  });

  it("hides the modal again when onClose fires; CTA stays visible", async () => {
    const user = userEvent.setup();
    render(
      <GenerateRoomCTA
        pathId="path-1"
        courseId="course-1"
        pathSlug="python-bootcamp"
      />,
    );

    await user.click(screen.getByTestId("generate-room-cta-dashboard-rail"));
    expect(screen.getByTestId("generate-room-modal")).toBeInTheDocument();

    await user.click(screen.getByTestId("generate-room-modal-close-stub"));
    expect(
      screen.queryByTestId("generate-room-modal"),
    ).not.toBeInTheDocument();
    // CTA is always present.
    expect(
      screen.getByTestId("generate-room-cta-dashboard-rail"),
    ).toBeInTheDocument();
  });

  // Phase 16b Bundle B v2 — distinct testid per variant so a page that
  // happens to render both layouts at once (or a test asserting the
  // track-detail mount specifically) can target without ambiguity.
  it("renders a distinct testid for the track-header variant", () => {
    render(
      <GenerateRoomCTA
        pathId="path-1"
        courseId="course-1"
        pathSlug="python-bootcamp"
        variant="track-header"
      />,
    );

    expect(
      screen.getByTestId("generate-room-cta-track-header"),
    ).toBeInTheDocument();
    // The default-variant testid must NOT be present in this render —
    // otherwise we'd be looking at a regression where every variant
    // emits the same id.
    expect(
      screen.queryByTestId("generate-room-cta-dashboard-rail"),
    ).not.toBeInTheDocument();
  });

  it("track-header variant also opens the modal on click", async () => {
    const user = userEvent.setup();
    render(
      <GenerateRoomCTA
        pathId="path-1"
        courseId="course-1"
        pathSlug="python-bootcamp"
        variant="track-header"
      />,
    );

    expect(
      screen.queryByTestId("generate-room-modal"),
    ).not.toBeInTheDocument();
    await user.click(screen.getByTestId("generate-room-cta-track-header"));
    expect(screen.getByTestId("generate-room-modal")).toBeInTheDocument();
  });
});
