import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LocaleProvider } from "@/lib/i18n-context";
import { WelcomeBackModal } from "./welcome-back-modal";
import type { WelcomeBackPayload } from "@/lib/api/welcome-back";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const getWelcomeBackMock = vi.fn();

vi.mock("@/lib/api/welcome-back", () => ({
  getWelcomeBack: () => getWelcomeBackMock(),
}));

const DISMISS_KEY = "ld:welcome-back:dismissed-until";

function payload(overrides: Partial<WelcomeBackPayload> = {}): WelcomeBackPayload {
  return {
    gap_days: 5,
    last_practice_at: "2026-04-15T09:00:00Z",
    top_mastered_concepts: ["Pointers", "Loops", "Iterators"],
    overdue_count: 4,
    ...overrides,
  };
}

function renderModal() {
  return render(
    <LocaleProvider>
      <WelcomeBackModal />
    </LocaleProvider>,
  );
}

describe("<WelcomeBackModal>", () => {
  beforeEach(() => {
    mockPush.mockReset();
    getWelcomeBackMock.mockReset();
    window.localStorage.clear();
  });

  it("stays hidden for a brand-new user (gap_days: null)", async () => {
    getWelcomeBackMock.mockResolvedValue(
      payload({ gap_days: null, last_practice_at: null }),
    );
    renderModal();
    // Let the fetch microtask flush.
    await Promise.resolve();
    await Promise.resolve();
    expect(
      screen.queryByTestId("welcome-back-modal"),
    ).not.toBeInTheDocument();
  });

  it("stays hidden when gap is below the 3-day threshold", async () => {
    getWelcomeBackMock.mockResolvedValue(payload({ gap_days: 2 }));
    renderModal();
    await Promise.resolve();
    await Promise.resolve();
    expect(
      screen.queryByTestId("welcome-back-modal"),
    ).not.toBeInTheDocument();
  });

  it("renders for a 5-day gap with the correct title", async () => {
    getWelcomeBackMock.mockResolvedValue(payload({ gap_days: 5 }));
    renderModal();
    await waitFor(() => {
      expect(screen.getByTestId("welcome-back-title")).toHaveTextContent(
        "Welcome back — it's been 5 days",
      );
    });
  });

  it("persists a future dismiss timestamp when the user clicks an action", async () => {
    getWelcomeBackMock.mockResolvedValue(payload({ gap_days: 5 }));
    const user = userEvent.setup();
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("welcome-back-modal")).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("welcome-back-one-card"));

    const stored = window.localStorage.getItem(DISMISS_KEY);
    expect(stored).not.toBeNull();
    const until = Number.parseInt(stored ?? "", 10);
    const now = Date.now();
    expect(until).toBeGreaterThan(now);
    // Tomorrow UTC midnight is at most ~25h out from any current wall
    // clock (24h + DST-like slack); plenty of headroom here.
    expect(until).toBeLessThan(now + 25 * 60 * 60 * 1000);
  });

  it("stays hidden when a future dismiss stamp is already set", async () => {
    window.localStorage.setItem(
      DISMISS_KEY,
      String(Date.now() + 60 * 60 * 1000),
    );
    getWelcomeBackMock.mockResolvedValue(payload({ gap_days: 5 }));
    renderModal();
    await Promise.resolve();
    await Promise.resolve();
    expect(
      screen.queryByTestId("welcome-back-modal"),
    ).not.toBeInTheDocument();
    // Fetch should be skipped when the dismiss stamp is still valid.
    expect(getWelcomeBackMock).not.toHaveBeenCalled();
  });

  it("navigates to /session/daily?size=1 when the 1-card button is clicked", async () => {
    getWelcomeBackMock.mockResolvedValue(payload({ gap_days: 5 }));
    const user = userEvent.setup();
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("welcome-back-modal")).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("welcome-back-one-card"));
    expect(mockPush).toHaveBeenCalledWith("/session/daily?size=1");
  });

  it("hides the review button when no mastered concepts are available", async () => {
    getWelcomeBackMock.mockResolvedValue(
      payload({ gap_days: 5, top_mastered_concepts: [] }),
    );
    renderModal();
    await waitFor(() =>
      expect(screen.getByTestId("welcome-back-modal")).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("welcome-back-review"),
    ).not.toBeInTheDocument();
  });
});
