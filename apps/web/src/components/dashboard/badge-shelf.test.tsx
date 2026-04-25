/**
 * Tests for `<BadgeShelf>` (Phase 16c Bundle C — Subagent B).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BadgeShelf } from "./badge-shelf";
import type { BadgeOut, BadgesResponse } from "@/lib/api/gamification";

const getBadgesMock = vi.fn();
vi.mock("@/lib/api/gamification", async () => ({
  getBadges: (...args: unknown[]) => getBadgesMock(...args),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  } & React.HTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function makeBadge(overrides: Partial<BadgeOut> = {}): BadgeOut {
  return {
    key: "first_card",
    title: "First Card",
    description: "Studied your first card.",
    hint: "Open a deck and review one card.",
    unlocked: false,
    unlocked_at: null,
    ...overrides,
  };
}

function makeResponse(
  unlocked: BadgeOut[],
  locked: BadgeOut[],
): BadgesResponse {
  return { unlocked, locked };
}

describe("<BadgeShelf>", () => {
  beforeEach(() => {
    getBadgesMock.mockReset();
  });

  it("renders the loading skeleton on initial mount", () => {
    // Pending promise so the loading branch stays mounted for the assertion.
    getBadgesMock.mockReturnValue(new Promise(() => {}));
    render(<BadgeShelf />);
    expect(screen.getByTestId("badge-shelf-skeleton")).toBeInTheDocument();
  });

  it("renders unlocked + locked badges with distinct styling", async () => {
    getBadgesMock.mockResolvedValue(
      makeResponse(
        [
          makeBadge({
            key: "first_card",
            title: "First Card",
            unlocked: true,
            unlocked_at: "2026-04-25T10:00:00Z",
          }),
        ],
        [
          makeBadge({
            key: "7_day_streak",
            title: "7-day Streak",
            unlocked: false,
          }),
        ],
      ),
    );
    render(<BadgeShelf />);

    await waitFor(() => {
      expect(screen.getByTestId("badge-shelf-grid")).toBeInTheDocument();
    });

    const unlocked = screen.getByTestId("badge-tile-first_card");
    const locked = screen.getByTestId("badge-tile-7_day_streak");
    expect(unlocked.getAttribute("data-unlocked")).toBe("true");
    expect(locked.getAttribute("data-unlocked")).toBe("false");
    expect(screen.getByTestId("badge-shelf-caption")).toHaveTextContent(
      "1 of 2 unlocked",
    );
  });

  it("shows 'No badges yet' empty copy when nothing is unlocked", async () => {
    getBadgesMock.mockResolvedValue(
      makeResponse(
        [],
        [
          makeBadge({ key: "first_card", title: "First Card" }),
          makeBadge({ key: "7_day_streak", title: "7-day Streak" }),
        ],
      ),
    );
    render(<BadgeShelf />);

    await waitFor(() => {
      expect(screen.getByTestId("badge-shelf-empty")).toHaveTextContent(
        "No badges yet. Keep learning.",
      );
    });
  });

  it("renders 'Show all' link to /profile/badges when total exceeds visible cap", async () => {
    // 9 locked badges → exceeds MAX_VISIBLE (8). Caption sees the full count;
    // the "Show all" anchor routes to the catalog page.
    const locked = Array.from({ length: 9 }, (_, i) =>
      makeBadge({ key: `b${i}`, title: `B${i}`, unlocked: false }),
    );
    getBadgesMock.mockResolvedValue(makeResponse([], locked));
    render(<BadgeShelf />);

    await waitFor(() => {
      const link = screen.getByTestId("badge-shelf-show-all");
      expect(link).toHaveAttribute("href", "/profile/badges");
    });
  });

  it("renders a retry button when the API rejects", async () => {
    const user = userEvent.setup();
    getBadgesMock.mockRejectedValueOnce(new Error("boom"));
    render(<BadgeShelf />);

    await waitFor(() => {
      expect(screen.getByTestId("badge-shelf-error")).toBeInTheDocument();
    });

    // Retry succeeds — the grid replaces the error row.
    getBadgesMock.mockResolvedValueOnce(
      makeResponse(
        [makeBadge({ key: "first_card", title: "First Card", unlocked: true })],
        [],
      ),
    );
    await user.click(screen.getByTestId("badge-shelf-retry"));

    await waitFor(() => {
      expect(screen.getByTestId("badge-shelf-grid")).toBeInTheDocument();
    });
  });
});
