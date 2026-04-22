import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DailySessionCTA } from "./daily-session-cta";
import { useDailySessionStore } from "@/store/daily-session";
import { LocaleProvider } from "@/lib/i18n-context";
import type { DailyPlan } from "@/lib/api";

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
vi.mock("@/lib/api", async () => {
  return {
    getDailyPlan: (...args: unknown[]) => getDailyPlanMock(...args),
  };
});

function renderWithProvider(ui: React.ReactElement) {
  return render(<LocaleProvider>{ui}</LocaleProvider>);
}

function makePlan(n: number, reason: string | null = null): DailyPlan {
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
    useDailySessionStore.getState().reset();
  });

  it("renders 3 size buttons", () => {
    renderWithProvider(<DailySessionCTA />);
    expect(screen.getByTestId("daily-session-cta-1")).toBeInTheDocument();
    expect(screen.getByTestId("daily-session-cta-5")).toBeInTheDocument();
    expect(screen.getByTestId("daily-session-cta-10")).toBeInTheDocument();
  });

  it("fetches, seeds store, and navigates on click", async () => {
    getDailyPlanMock.mockResolvedValue(makePlan(5));
    const user = userEvent.setup();
    renderWithProvider(<DailySessionCTA />);

    await user.click(screen.getByTestId("daily-session-cta-5"));

    await waitFor(() => {
      expect(getDailyPlanMock).toHaveBeenCalledWith(5);
    });
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/session/daily");
    });
    expect(useDailySessionStore.getState().cards).toHaveLength(5);
    expect(useDailySessionStore.getState().size).toBe(5);
  });

  it("shows no-guilt empty line when backend reports nothing_due", async () => {
    getDailyPlanMock.mockResolvedValue(makePlan(0, "nothing_due"));
    const user = userEvent.setup();
    renderWithProvider(<DailySessionCTA />);

    await user.click(screen.getByTestId("daily-session-cta-1"));

    await waitFor(() => {
      expect(screen.getByText(/nothing due/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/come back later/i)).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
    expect(useDailySessionStore.getState().cards).toHaveLength(0);
  });

  it("surfaces an inline error on fetch failure without navigating", async () => {
    getDailyPlanMock.mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    renderWithProvider(<DailySessionCTA />);

    await user.click(screen.getByTestId("daily-session-cta-10"));

    await waitFor(() => {
      expect(screen.getByTestId("daily-session-cta-error")).toHaveTextContent(
        /boom/,
      );
    });
    expect(mockPush).not.toHaveBeenCalled();
    // Buttons re-enabled after failure so the user can retry.
    expect(screen.getByTestId("daily-session-cta-10")).not.toBeDisabled();
  });

  it("disables all buttons while a fetch is in flight", async () => {
    let resolve: ((v: DailyPlan) => void) | undefined;
    getDailyPlanMock.mockImplementation(
      () =>
        new Promise<DailyPlan>((r) => {
          resolve = r;
        }),
    );
    const user = userEvent.setup();
    renderWithProvider(<DailySessionCTA />);

    await user.click(screen.getByTestId("daily-session-cta-5"));

    expect(screen.getByTestId("daily-session-cta-1")).toBeDisabled();
    expect(screen.getByTestId("daily-session-cta-5")).toBeDisabled();
    expect(screen.getByTestId("daily-session-cta-10")).toBeDisabled();

    resolve?.(makePlan(5));
    await waitFor(() => expect(mockPush).toHaveBeenCalled());
  });
});
