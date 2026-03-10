import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { FlashcardView } from "./flashcard-view";

const MOCK_CARDS = [
  { id: "c1", front: "What is 2+2?", back: "4", interval: 1, ease_factor: 2.5, repetitions: 0 },
  { id: "c2", front: "Capital of France?", back: "Paris", interval: 1, ease_factor: 2.5, repetitions: 0 },
];

vi.mock("@/lib/api", async () => {
  const cards = [
    { id: "c1", front: "What is 2+2?", back: "4", interval: 1, ease_factor: 2.5, repetitions: 0 },
    { id: "c2", front: "Capital of France?", back: "Paris", interval: 1, ease_factor: 2.5, repetitions: 0 },
  ];
  return {
    getDueFlashcards: vi.fn().mockResolvedValue({ cards, due_count: 2 }),
    generateFlashcards: vi.fn().mockResolvedValue({ cards, count: 2 }),
    reviewFlashcard: vi.fn().mockResolvedValue({}),
    saveGeneratedFlashcards: vi.fn().mockResolvedValue({}),
    listGeneratedFlashcardBatches: vi.fn().mockResolvedValue([]),
  };
});

vi.mock("@/lib/api/practice", async () => {
  const cards = [
    { id: "c1", front: "What is 2+2?", back: "4", interval: 1, ease_factor: 2.5, repetitions: 0 },
    { id: "c2", front: "Capital of France?", back: "Paris", interval: 1, ease_factor: 2.5, repetitions: 0 },
  ];
  return {
    getLectorOrderedFlashcards: vi.fn().mockResolvedValue({ cards, count: 2 }),
  };
});

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

describe("FlashcardView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state initially", () => {
    render(<FlashcardView courseId="test-course" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
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
      expect(screen.getByRole("button", { name: /flashcard showing question/i })).toBeInTheDocument();
    });
  });

  it("flips card on click", async () => {
    render(<FlashcardView courseId="test-course" />);
    await waitFor(() => screen.getByText("What is 2+2?"));

    const card = screen.getByRole("button", { name: /flashcard showing question/i });
    fireEvent.click(card);

    expect(screen.getByRole("button", { name: /flashcard showing answer/i })).toBeInTheDocument();
  });

  it("flips card on Enter key", async () => {
    render(<FlashcardView courseId="test-course" />);
    await waitFor(() => screen.getByText("What is 2+2?"));

    const card = screen.getByRole("button", { name: /flashcard showing question/i });
    fireEvent.keyDown(card, { key: "Enter" });

    expect(screen.getByRole("button", { name: /flashcard showing answer/i })).toBeInTheDocument();
  });

  it("shows rating buttons after flip", async () => {
    render(<FlashcardView courseId="test-course" />);
    await waitFor(() => screen.getByText("What is 2+2?"));

    fireEvent.click(screen.getByRole("button", { name: /flashcard showing question/i }));

    expect(screen.getByRole("button", { name: /Rate: Again/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rate: Good/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rate: Easy/ })).toBeInTheDocument();
  });

  it("advances to next card after rating", async () => {
    const { reviewFlashcard } = await import("@/lib/api");
    render(<FlashcardView courseId="test-course" />);
    await waitFor(() => screen.getByText("What is 2+2?"));

    fireEvent.click(screen.getByRole("button", { name: /flashcard showing question/i }));
    fireEvent.click(screen.getByRole("button", { name: /Rate: Good/ }));

    await waitFor(() => {
      expect(reviewFlashcard).toHaveBeenCalledWith(MOCK_CARDS[0], 3);
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
    fireEvent.click(screen.getByRole("button", { name: /flashcard showing question/i }));
    fireEvent.click(screen.getByRole("button", { name: /Rate: Good/ }));

    await waitFor(() => screen.getByText("Capital of France?"));

    // Review second card
    fireEvent.click(screen.getByRole("button", { name: /flashcard showing question/i }));
    fireEvent.click(screen.getByRole("button", { name: /Rate: Easy/ }));

    await waitFor(() => {
      expect(screen.getByText(/all done/i)).toBeInTheDocument();
    });
  });

  it("has role=region with aria-label", async () => {
    render(<FlashcardView courseId="test-course" />);
    await waitFor(() => screen.getByText("What is 2+2?"));
    expect(screen.getByRole("region", { name: "flashcard.title" })).toBeInTheDocument();
  });
});
