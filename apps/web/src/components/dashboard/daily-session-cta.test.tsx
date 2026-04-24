import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { DailyPlan, DailyPlanReason } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n-context";
import { useBadDayStore } from "@/store/bad-day";
import { useDailySessionStore } from "@/store/daily-session";

import { DailySessionCTA } from "./daily-session-cta";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const getDailyPlanMock = vi.fn();
vi.mock("@/lib/api", async () => ({
  getDailyPlan: (...args: unknown[]) => getDailyPlanMock(...args),
}));

function renderWithProvider(ui: React.ReactElement) {
  return render(<LocaleProvider>{ui}</LocaleProvider>);
}

function todayUtc() {
  return new Date().toISOString().slice(0, 10);
}

function makePlan(n: number, reason: DailyPlanReason | null = null): DailyPlan {
  return {
    cards: Array.from({ length: n }, (_, i) => ({
      id: `card-${i}`,
      question_type: "multiple_choice",
      question: `Q${i}`,
      options: { a: "A", b: "B" },
      correct_answer: null,
      explanation: null,
      difficulty_layer: 1,
      content_node_id: null,
      problem_metadata: null,
    })),
    size: n,
    reason,
  };
}

describe("<DailySessionCTA>", () => {
  beforeEach(() => {
    mockPush.mockReset();
    getDailyPlanMock.mockReset();
    window.localStorage.clear();
    useDailySessionStore.getState().reset();
    useBadDayStore.setState({ active: false, activated_date: "" });
  });

  it("renders 3 size buttons", () => {
    renderWithProvider(<DailySessionCTA />);

    expect(screen.getByTestId("daily-session-cta-1")).toBeInTheDocument();
    expect(screen.getByTestId("daily-session-cta-5")).toBeInTheDocument();
    expect(screen.getByTestId("daily-session-cta-10")).toBeInTheDocument();
  });

  it("fetches, seeds store, and navigates on click", async () => {
    getDailyPlanMock.mockResolvedValue(makePlan(5));

    renderWithProvider(<DailySessionCTA />);
    fireEvent.click(screen.getByTestId("daily-session-cta-5"));

    await waitFor(() => {
      expect(getDailyPlanMock).toHaveBeenCalledWith(5);
    });
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/session/daily");
    });

    expect(useDailySessionStore.getState().cards).toHaveLength(5);
    expect(useDailySessionStore.getState().size).toBe(5);
  });

  it("shows the bad-day chip and requests easy_only when active", async () => {
    useBadDayStore.setState({
      active: true,
      activated_date: todayUtc(),
    });
    getDailyPlanMock.mockResolvedValue(makePlan(5));

    renderWithProvider(<DailySessionCTA />);

    expect(
      screen.getByTestId("daily-session-cta-bad-day-chip"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("daily-session-cta-5"));

    await waitFor(() => {
      expect(getDailyPlanMock).toHaveBeenCalledWith(5, {
        strategy: "easy_only",
      });
    });
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/session/daily?strategy=easy_only");
    });
  });

  it("shows the softer empty state for bad_day_empty", async () => {
    useBadDayStore.setState({
      active: true,
      activated_date: todayUtc(),
    });
    getDailyPlanMock.mockResolvedValue(makePlan(0, "bad_day_empty"));

    renderWithProvider(<DailySessionCTA />);
    fireEvent.click(screen.getByTestId("daily-session-cta-1"));

    await waitFor(() => {
      expect(screen.getByText(/nothing easy due/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/turn off easy mode/i)).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
  });
});
