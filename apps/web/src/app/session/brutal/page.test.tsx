import { StrictMode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import BrutalSessionPage from "./page";
import { LocaleProvider } from "@/lib/i18n-context";
import { useBrutalSessionStore } from "@/store/brutal-session";
import type { BrutalPlanResponse, DailyPlanCard } from "@/lib/api";

const mockPush = vi.fn();
const mockReplace = vi.fn();
const mockSearchParams = new URLSearchParams("size=20&timeout=30");
const mockRouter = {
  push: (...args: unknown[]) => mockPush(...args),
  replace: (...args: unknown[]) => mockReplace(...args),
  back: vi.fn(),
  forward: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
};

vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
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

describe("/session/brutal page", () => {
  beforeEach(() => {
    mockPush.mockReset();
    mockReplace.mockReset();
    getBrutalPlanMock.mockReset();
    submitAnswerMock.mockReset();
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
});
