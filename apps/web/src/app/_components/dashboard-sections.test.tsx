import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LocaleProvider } from "@/lib/i18n-context";
import {
  UrgentReviewsSection,
  FlashcardsDueSection,
} from "./dashboard-sections";
import type { ReviewSummary } from "./dashboard-utils";

function renderWithProvider(ui: React.ReactElement) {
  return render(<LocaleProvider>{ui}</LocaleProvider>);
}

// tf mock replicates the interpolation behaviour of rawTF — we use the
// real provider-context t/tf for the clamp labels so the assertions hit
// the same code path as production.
function makeReview(i: number): ReviewSummary {
  return {
    courseId: `c-${i}`,
    courseName: `Course ${i}`,
    overdueCount: 1,
    urgentCount: 0,
    totalCount: 2,
  };
}

// The real app threads t/tf through props from the dashboard page (which
// reads from the locale bundle). Simulate that here so clamp labels
// render with the actual en.json copy.
import en from "@/locales/en.json";

function t(key: string): string {
  return (en as Record<string, string>)[key] ?? key;
}
function tf(key: string, vars?: Record<string, string | number | null | undefined>): string {
  let s = t(key);
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      s = s.replace(`{${k}}`, String(v));
    }
  }
  return s;
}

describe("<UrgentReviewsSection> clamp (Phase 13 T6)", () => {
  const noop = () => {};

  it("shows all items and no toggle when ≤3 reviews", () => {
    const reviews = [makeReview(0), makeReview(1), makeReview(2)];
    renderWithProvider(
      <UrgentReviewsSection
        reviewSummaries={reviews}
        totalUrgentReviews={3}
        onNavigate={noop}
        t={t}
        tf={tf}
      />,
    );
    expect(screen.getByText("Course 0")).toBeInTheDocument();
    expect(screen.getByText("Course 2")).toBeInTheDocument();
    expect(screen.queryByTestId("urgent-reviews-toggle")).toBeNull();
  });

  it("hides items past 3 behind a toggle when >3 reviews", () => {
    const reviews = [0, 1, 2, 3, 4].map(makeReview);
    renderWithProvider(
      <UrgentReviewsSection
        reviewSummaries={reviews}
        totalUrgentReviews={5}
        onNavigate={noop}
        t={t}
        tf={tf}
      />,
    );
    expect(screen.getByText("Course 0")).toBeInTheDocument();
    expect(screen.getByText("Course 2")).toBeInTheDocument();
    expect(screen.queryByText("Course 3")).toBeNull();
    expect(screen.queryByText("Course 4")).toBeNull();

    const toggle = screen.getByTestId("urgent-reviews-toggle");
    expect(toggle).toHaveTextContent("+ 2 more");
    // §8 touch-target guideline
    expect(toggle.className).toMatch(/min-h-\[44px\]/);
  });

  it("expands to show all items when toggle is clicked, then collapses", async () => {
    const reviews = [0, 1, 2, 3, 4].map(makeReview);
    const user = userEvent.setup();
    renderWithProvider(
      <UrgentReviewsSection
        reviewSummaries={reviews}
        totalUrgentReviews={5}
        onNavigate={noop}
        t={t}
        tf={tf}
      />,
    );

    await user.click(screen.getByTestId("urgent-reviews-toggle"));
    expect(screen.getByText("Course 3")).toBeInTheDocument();
    expect(screen.getByText("Course 4")).toBeInTheDocument();
    expect(screen.getByTestId("urgent-reviews-toggle")).toHaveTextContent(
      /show fewer/i,
    );

    await user.click(screen.getByTestId("urgent-reviews-toggle"));
    expect(screen.queryByText("Course 3")).toBeNull();
  });
});

describe("<FlashcardsDueSection> clamp (Phase 13 T6)", () => {
  const noop = () => {};

  function makeFlashcardDue(i: number, due = 2) {
    return { courseId: `fc-${i}`, courseName: `FC ${i}`, dueCount: due };
  }

  it("shows the raw number when total is at or below 10", () => {
    renderWithProvider(
      <FlashcardsDueSection
        flashcardDueByCourse={[makeFlashcardDue(0, 7)]}
        totalDueFlashcards={7}
        onNavigate={noop}
        t={t}
        tf={tf}
      />,
    );
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.queryByTestId("flashcards-due-clamp-label")).toBeNull();
  });

  it("displays '10+' and the batch label when total exceeds 10", () => {
    renderWithProvider(
      <FlashcardsDueSection
        flashcardDueByCourse={[makeFlashcardDue(0, 25)]}
        totalDueFlashcards={25}
        onNavigate={noop}
        t={t}
        tf={tf}
      />,
    );
    expect(screen.getByText("10+")).toBeInTheDocument();
    expect(screen.getByTestId("flashcards-due-clamp-label")).toBeInTheDocument();
    // raw 25 must NOT be visible (that's the "loud counter" we're fixing)
    expect(screen.queryByText("25")).toBeNull();
  });

  it("does not clamp exactly at the 10 boundary", () => {
    renderWithProvider(
      <FlashcardsDueSection
        flashcardDueByCourse={[makeFlashcardDue(0, 10)]}
        totalDueFlashcards={10}
        onNavigate={noop}
        t={t}
        tf={tf}
      />,
    );
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.queryByTestId("flashcards-due-clamp-label")).toBeNull();
  });
});
