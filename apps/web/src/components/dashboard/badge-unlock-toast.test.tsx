/**
 * Tests for `<BadgeUnlockToast>` (Phase 16c Bundle C — Subagent B).
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BadgeUnlockToast } from "./badge-unlock-toast";
import type { BadgeOut } from "@/lib/api/gamification";

function makeBadge(overrides: Partial<BadgeOut> = {}): BadgeOut {
  return {
    key: "first_card",
    title: "First Card",
    description: "Studied your first card.",
    hint: "Open a deck and review one card.",
    unlocked: true,
    unlocked_at: "2026-04-25T10:00:00Z",
    ...overrides,
  };
}

describe("<BadgeUnlockToast>", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing when badge is null", () => {
    const onDismiss = vi.fn();
    const { container } = render(
      <BadgeUnlockToast badge={null} onDismiss={onDismiss} />,
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("badge-unlock-toast")).not.toBeInTheDocument();
  });

  it("renders title and description for a provided badge", () => {
    const onDismiss = vi.fn();
    render(
      <BadgeUnlockToast
        badge={makeBadge({
          title: "7-day Streak",
          description: "Studied seven days in a row.",
        })}
        onDismiss={onDismiss}
      />,
    );

    expect(screen.getByTestId("badge-unlock-toast")).toBeInTheDocument();
    expect(screen.getByTestId("badge-unlock-toast-title")).toHaveTextContent(
      "Unlocked: 7-day Streak",
    );
    expect(
      screen.getByText("Studied seven days in a row."),
    ).toBeInTheDocument();
  });

  it("calls onDismiss after autoDismissMs elapses", () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    render(
      <BadgeUnlockToast
        badge={makeBadge()}
        onDismiss={onDismiss}
        autoDismissMs={3000}
      />,
    );

    expect(onDismiss).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("calls onDismiss when the user clicks the dismiss button", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(<BadgeUnlockToast badge={makeBadge()} onDismiss={onDismiss} />);

    await user.click(screen.getByTestId("badge-unlock-toast-dismiss"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
