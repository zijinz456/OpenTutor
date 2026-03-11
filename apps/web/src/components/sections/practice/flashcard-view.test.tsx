import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { FlashcardView } from "./flashcard-view";

function freshCards() {
  return [
    { id: "c1", front: "What is 2+2?", back: "4", interval: 1, ease_factor: 2.5, repetitions: 0 },
    { id: "c2", front: "Capital of France?", back: "Paris", interval: 1, ease_factor: 2.5, repetitions: 0 },
  ];
}

vi.mock("@/lib/api", () => ({
  getDueFlashcards: vi.fn(),
  generateFlashcards: vi.fn(),
  reviewFlashcard: vi.fn(),
  saveGeneratedFlashcards: vi.fn(),
  listGeneratedFlashcardBatches: vi.fn(),
}));

vi.mock("@/lib/api/practice", () => ({
  getLectorOrderedFlashcards: vi.fn(),
}));

vi.mock("@/lib/i18n-context", () => ({
  useT: () => (key: string) => key,
  useTF: () => (key: string) => key,
}));

vi.mock("@/store/workspace", () => ({
  useWorkspaceStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector({ sectionRefreshKey: { practice: 0 }, spaceLayout: { mode: "self_paced" } }),
    { getState: () => ({ sectionRefreshKey: { practice: 0 }, spaceLayout: { mode: "self_paced" } }) },
  ),
}));

vi.mock("@/hooks/use-batch-manager", () => ({
  useBatchManager: () => ({ saving: false, latestBatch: null, wrapSave: vi.fn() }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/components/shared/ai-feature-blocked", () => ({
  AiFeatureBlocked: () => <div data-testid="ai-blocked" />,
}));

vi.mock("./use-quiz-persistence", () => ({
  useQuizPersistence: () => ({ save: vi.fn(), load: vi.fn().mockReturnValue(null), clear: vi.fn() }),
  useFlashcardPersistence: () => ({ save: vi.fn(), load: vi.fn().mockReturnValue(null), clear: vi.fn() }),
}));

describe("FlashcardView", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    const api = await import("@/lib/api");
    const practice = await import("@/lib/api/practice");
    (api.getDueFlashcards as ReturnType<typeof vi.fn>).mockResolvedValue({ cards: freshCards(), due_count: 2 });
    (api.generateFlashcards as ReturnType<typeof vi.fn>).mockResolvedValue({ cards: freshCards(), count: 2 });
    (api.reviewFlashcard as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (api.saveGeneratedFlashcards as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (api.listGeneratedFlashcardBatches as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (practice.getLectorOrderedFlashcards as ReturnType<typeof vi.fn>).mockResolvedValue({ cards: freshCards(), count: 2 });
  });

  it("renders loading state initially", async () => {
    render(<FlashcardView courseId="test-course" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });
  });

  it("renders flashcard question after loading", async () => {
    render(<FlashcardView courseId="test-course" />);
    await waitFor(() => {
      expect(screen.getByText("What is 2+2?")).toBeInTheDocument();
    });
  });

  it("has accessible flashcard button", async () => {
    render(<FlashcardView courseId="test-course" />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /flashcard\.ariaQuestion/ })).toBeInTheDocument();
    });
  });

  it("flips card on click", async () => {
    render(<FlashcardView courseId="test-course" />);
    await waitFor(() => screen.getByText("What is 2+2?"));

    const card = screen.getByRole("button", { name: /flashcard\.ariaQuestion/ });
    fireEvent.click(card);

    expect(screen.getByRole("button", { name: /flashcard\.ariaAnswer/ })).toBeInTheDocument();
  });

  it("flips card on Enter key", async () => {
    render(<FlashcardView courseId="test-course" />);
    await waitFor(() => screen.getByText("What is 2+2?"));

    const card = screen.getByRole("button", { name: /flashcard\.ariaQuestion/ });
    fireEvent.keyDown(card, { key: "Enter" });

    expect(screen.getByRole("button", { name: /flashcard\.ariaAnswer/ })).toBeInTheDocument();
  });

  it("shows rating buttons after flip", async () => {
    render(<FlashcardView courseId="test-course" />);
    await waitFor(() => screen.getByText("What is 2+2?"));

    fireEvent.click(screen.getByRole("button", { name: /flashcard\.ariaQuestion/ }));

    expect(screen.getByRole("button", { name: /Rate: flashcard\.again/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rate: flashcard\.good/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rate: flashcard\.easy/ })).toBeInTheDocument();
  });

  it("advances to next card after rating", async () => {
    const { reviewFlashcard } = await import("@/lib/api");
    render(<FlashcardView courseId="test-course" />);
    await waitFor(() => screen.getByText("What is 2+2?"));

    fireEvent.click(screen.getByRole("button", { name: /flashcard\.ariaQuestion/ }));
    fireEvent.click(screen.getByRole("button", { name: /Rate: flashcard\.good/ }));

    await waitFor(() => {
      expect(reviewFlashcard).toHaveBeenCalledWith(
        expect.objectContaining({ id: "c1", front: "What is 2+2?" }), 3
      );
    });

    await waitFor(() => {
      expect(screen.getByText("Capital of France?")).toBeInTheDocument();
    });
  });

  it("shows completion message after all cards reviewed", async () => {
    const { reviewFlashcard } = await import("@/lib/api");
    (reviewFlashcard as ReturnType<typeof vi.fn>).mockResolvedValue({});

    render(<FlashcardView courseId="test-course" />);
    await waitFor(() => screen.getByText("What is 2+2?"));

    // Review first card
    fireEvent.click(screen.getByRole("button", { name: /flashcard\.ariaQuestion/ }));
    fireEvent.click(screen.getByRole("button", { name: /Rate: flashcard\.good/ }));

    await waitFor(() => screen.getByText("Capital of France?"));

    // Review second card
    fireEvent.click(screen.getByRole("button", { name: /flashcard\.ariaQuestion/ }));
    fireEvent.click(screen.getByRole("button", { name: /Rate: flashcard\.easy/ }));

    await waitFor(() => {
      expect(screen.getByText(/flashcard\.allDone/)).toBeInTheDocument();
    });
  });

  it("has role=region with aria-label", async () => {
    render(<FlashcardView courseId="test-course" />);
    await waitFor(() => screen.getByText("What is 2+2?"));
    expect(screen.getByRole("region", { name: "flashcard.title" })).toBeInTheDocument();
  });
});
