import { StrictMode, useEffect, useState, type ReactNode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import BrutalSessionPage from "./page";
import { LocaleProvider } from "@/lib/i18n-context";
import { useBrutalSessionStore } from "@/store/brutal-session";
import type { BrutalPlanResponse, DailyPlanCard } from "@/lib/api";

const mockPush = vi.fn();
const mockReplace = vi.fn();
const mockSearchParams = new URLSearchParams("size=20&timeout=30");
let useFreshRouterEachRender = false;
const mockRouter = {
  push: (...args: unknown[]) => mockPush(...args),
  replace: (...args: unknown[]) => mockReplace(...args),
  back: vi.fn(),
  forward: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
};

vi.mock("next/navigation", () => ({
  useRouter: () => (useFreshRouterEachRender ? { ...mockRouter } : mockRouter),
  useSearchParams: () => mockSearchParams,
}));

const getBrutalPlanMock = vi.fn();
const submitAnswerMock = vi.fn();

vi.mock("@/lib/api", async () => ({
  getBrutalPlan: (...args: unknown[]) => getBrutalPlanMock(...args),
  submitAnswer: (...args: unknown[]) => submitAnswerMock(...args),
}));

vi.mock("@/components/session/brutal-timer-ring", () => ({
  BrutalTimerRing: () => <div data-testid="brutal-timer-ring" />,
}));

vi.mock("@/components/session/brutal-closure", () => ({
  BrutalClosure: () => <div data-testid="brutal-closure" />,
}));

function makeCard(id: string, question: string): DailyPlanCard {
  return {
    id,
    question_type: "multiple_choice",
    question,
    options: { a: "Alpha", b: "Bravo", c: "Charlie" },
    correct_answer: "a",
    explanation: null,
    difficulty_layer: 1,
    content_node_id: null,
    problem_metadata: { concept_slug: "asyncio" },
  };
}

function makePlan(cards: DailyPlanCard[]): BrutalPlanResponse {
  return {
    cards,
    size: cards.length as BrutalPlanResponse["size"],
    strategy: "struggle_first",
    warning: null,
  };
}

function renderWithProvider() {
  return render(
    <LocaleProvider>
      <BrutalSessionPage />
    </LocaleProvider>,
  );
}

function renderStrictWithProvider() {
  return render(
    <StrictMode>
      <LocaleProvider>
        <BrutalSessionPage />
      </LocaleProvider>
    </StrictMode>,
  );
}

function RerenderHarness({ children }: { children: ReactNode }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    setTick((tick) => tick + 1);
  }, []);
  return <>{children}</>;
}

describe("/session/brutal page", () => {
  beforeEach(() => {
    mockPush.mockReset();
    mockReplace.mockReset();
    getBrutalPlanMock.mockReset();
    submitAnswerMock.mockReset();
    useFreshRouterEachRender = false;
    useBrutalSessionStore.getState().reset();
  });

  it("brutal-session-loading-recovery renders the first card after a successful boot fetch", async () => {
    getBrutalPlanMock.mockResolvedValue(
      makePlan([
        makeCard("b1", "First brutal question?"),
        makeCard("b2", "Second brutal question?"),
      ]),
    );

    renderStrictWithProvider();

    await waitFor(() =>
      expect(screen.getByTestId("brutal-session-question")).toHaveTextContent(
        "First brutal question?",
      ),
    );

    expect(screen.queryByTestId("brutal-session-loading")).toBeNull();
    expect(screen.queryByTestId("brutal-session-transition")).toBeNull();
    expect(getBrutalPlanMock).toHaveBeenCalledWith(20);
  });

  it("shows a visible loading label while the boot fetch is in flight", async () => {
    // Never-resolving promise so the loading branch stays rendered.
    getBrutalPlanMock.mockImplementation(() => new Promise(() => {}));

    renderWithProvider();

    expect(screen.getByTestId("brutal-session-loading")).toBeInTheDocument();
    expect(screen.getByText(/Loading drill/i)).toBeInTheDocument();
  });

  it("keeps the first resolved plan through a mount-time rerender", async () => {
    useFreshRouterEachRender = true;

    let resolveFirstPlan: ((plan: BrutalPlanResponse) => void) | null = null;
    getBrutalPlanMock
      .mockImplementationOnce(
        () =>
          new Promise<BrutalPlanResponse>((resolve) => {
            resolveFirstPlan = resolve;
          }),
      )
      .mockImplementationOnce(() => new Promise(() => {}));

    render(
      <RerenderHarness>
        <LocaleProvider>
          <BrutalSessionPage />
        </LocaleProvider>
      </RerenderHarness>,
    );

    expect(screen.getByTestId("brutal-session-loading")).toBeInTheDocument();

    await act(async () => {
      resolveFirstPlan?.(
        makePlan([
          makeCard("b1", "First brutal question?"),
          makeCard("b2", "Second brutal question?"),
        ]),
      );
      await Promise.resolve();
    });

    await waitFor(() =>
      expect(screen.getByTestId("brutal-session-question")).toHaveTextContent(
        "First brutal question?",
      ),
    );

    expect(getBrutalPlanMock).toHaveBeenCalledTimes(1);
  });

  it(
    "falls over to an error state if the boot fetch hangs past the safety timeout",
    async () => {
      // Regression: 2026-04-24 user report — /session/brutal hung on the
      // blank loading shell for 15s+ while API returned 200. A never-
      // resolving fetch must surface an actionable error instead of a
      // silent spinner.
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        getBrutalPlanMock.mockImplementation(() => new Promise(() => {}));

        renderWithProvider();

        expect(
          screen.getByTestId("brutal-session-loading"),
        ).toBeInTheDocument();

        // Bootstrap safety timer is 10s. Advance past it.
        await act(async () => {
          await vi.advanceTimersByTimeAsync(10_100);
        });

        await waitFor(() =>
          expect(screen.getByTestId("brutal-session-error")).toBeInTheDocument(),
        );
        expect(screen.getByRole("alert")).toHaveTextContent(/too long/i);
      } finally {
        vi.useRealTimers();
      }
    },
    15_000,
  );
});
