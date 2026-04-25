/**
 * Tests for the `/profile/badges` catalog page
 * (Phase 16c Bundle C — Subagent B).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import ProfileBadgesPage from "./page";
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

describe("/profile/badges page", () => {
  beforeEach(() => {
    getBadgesMock.mockReset();
  });

  it("renders the loading skeleton on initial mount", () => {
    getBadgesMock.mockReturnValue(new Promise(() => {}));
    render(<ProfileBadgesPage />);
    expect(screen.getByTestId("profile-badges-loading")).toBeInTheDocument();
    expect(screen.getByTestId("profile-badges-page")).toBeInTheDocument();
  });

  it("renders unlocked + locked sections with correct counts", async () => {
    getBadgesMock.mockResolvedValue(
      makeResponse(
        [
          makeBadge({
            key: "first_card",
            title: "First Card",
            unlocked: true,
            unlocked_at: "2026-04-25T10:00:00Z",
          }),
          makeBadge({
            key: "100_xp",
            title: "100 XP",
            unlocked: true,
            unlocked_at: "2026-04-24T10:00:00Z",
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
    render(<ProfileBadgesPage />);

    await waitFor(() => {
      expect(screen.getByTestId("profile-badges-unlocked")).toBeInTheDocument();
    });

    expect(screen.getByTestId("profile-badges-unlocked-count")).toHaveTextContent(
      "2",
    );
    expect(screen.getByTestId("profile-badges-locked-count")).toHaveTextContent(
      "1",
    );
    expect(
      screen.getByTestId("profile-badges-tile-first_card"),
    ).toHaveAttribute("data-unlocked", "true");
    expect(
      screen.getByTestId("profile-badges-tile-7_day_streak"),
    ).toHaveAttribute("data-unlocked", "false");
  });

  it("still renders the Locked section when no badges are unlocked", async () => {
    getBadgesMock.mockResolvedValue(
      makeResponse(
        [],
        [
          makeBadge({
            key: "7_day_streak",
            title: "7-day Streak",
            unlocked: false,
          }),
        ],
      ),
    );
    render(<ProfileBadgesPage />);

    await waitFor(() => {
      expect(screen.getByTestId("profile-badges-locked")).toBeInTheDocument();
    });

    // Unlocked section is mounted but renders the calm empty copy.
    expect(screen.getByTestId("profile-badges-unlocked")).toBeInTheDocument();
    expect(
      screen.getByText("No badges yet. Keep learning."),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("profile-badges-tile-7_day_streak"),
    ).toBeInTheDocument();
  });
});
