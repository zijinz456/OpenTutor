import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import DashboardPage from "./page";

const useDashboardDataMock = vi.fn();

vi.mock("@/lib/i18n-context", () => ({
  useLocale: () => ({ locale: "en" }),
}));

vi.mock("./_hooks/use-dashboard-data", () => ({
  useDashboardData: () => useDashboardDataMock(),
}));

vi.mock("@/components/shared/runtime-alert", () => ({
  RuntimeAlert: () => <div data-testid="runtime-alert" />,
}));

vi.mock("@/components/dashboard/welcome-back-modal", () => ({
  WelcomeBackModal: () => <div data-testid="welcome-back-modal" />,
}));

vi.mock("@/components/dashboard/continue-mission-hero", () => ({
  ContinueMissionHero: () => <div data-testid="continue-mission-hero" />,
}));

vi.mock("@/components/dashboard/daily-session-cta", () => ({
  DailySessionCTA: () => <div data-testid="daily-session-cta" />,
}));

vi.mock("@/components/dashboard/LearningPathsPill", () => ({
  LearningPathsPill: () => <div data-testid="learning-paths-pill" />,
}));

vi.mock("@/components/dashboard/DrillCoursesPill", () => ({
  DrillCoursesPill: () => <div data-testid="drill-courses-pill" />,
}));

vi.mock("@/components/dashboard/brutal-drill-cta", () => ({
  BrutalDrillCTA: () => <div data-testid="brutal-drill-cta" />,
}));

vi.mock("./_components/dash-section", () => ({
  CourseCardsSkeleton: () => <div data-testid="course-cards-skeleton" />,
}));

vi.mock("./_components/digest-fallback", () => ({
  LearningRhythm: () => <div data-testid="learning-rhythm" />,
}));

vi.mock("./_components/dashboard-sections", () => ({
  OverviewStats: () => <div data-testid="overview-stats" />,
  TodayDigestSection: () => <div data-testid="today-digest-section" />,
  UpcomingDeadlinesSection: () => <div data-testid="upcoming-deadlines-section" />,
  UrgentReviewsSection: () => <div data-testid="urgent-reviews-section" />,
  FlashcardsDueSection: () => <div data-testid="flashcards-due-section" />,
  KnowledgeDensitySection: () => <div data-testid="knowledge-density-section" />,
  AgentInsightsSection: () => <div data-testid="agent-insights-section" />,
  PendingApprovalsSection: () => <div data-testid="pending-approvals-section" />,
  ModeRecommendationsSection: () => <div data-testid="mode-recommendations-section" />,
  WeeklyStatsSection: () => <div data-testid="weekly-stats-section" />,
  MasteryOverviewSection: () => <div data-testid="mastery-overview-section" />,
}));

vi.mock("./_components/dashboard-spaces", () => ({
  CourseSpacesSection: () => <div data-testid="course-spaces-section" />,
  DashboardEmptyState: () => <div data-testid="dashboard-empty-state" />,
}));

function makeDashboardData(overrides: Record<string, unknown> = {}) {
  return {
    router: { push: vi.fn() },
    t: (key: string) =>
      ({
        "dashboard.title": "Dashboard",
        "dashboard.subtitle": "Stay on track",
        "dashboard.create": "Create",
        "dashboard.loadErrorPrefix": "Could not load",
        "home.deadline.overdue": "Overdue",
        "home.deadline.tomorrow": "Tomorrow",
      }[key] ?? key),
    tf: (key: string, values: { days: number }) =>
      key === "home.deadline.inDays" ? `In ${values.days} days` : key,
    courses: [{ id: "course-1", name: "Python" }],
    loading: false,
    error: null,
    health: null,
    reviewSummaries: [],
    notifications: [],
    pendingTasks: [],
    actingTasks: new Set<string>(),
    modeRecommendations: [],
    actingModeCourses: new Set<string>(),
    upcomingDeadlines: [],
    dailyDigest: null,
    knowledgeDensity: null,
    weeklyReport: null,
    masteryOverview: null,
    flashcardDueByCourse: [],
    totalDueFlashcards: 0,
    totalActiveGoals: 0,
    totalPendingApprovals: 0,
    totalRunningTasks: 0,
    totalUrgentReviews: 0,
    actOnTask: vi.fn(),
    applyModeRecommendation: vi.fn(),
    dismissModeRecommendation: vi.fn(),
    ...overrides,
  };
}

describe("/ page", () => {
  beforeEach(() => {
    useDashboardDataMock.mockReset();
  });

  it("renders the mission-first hero, 3-card row, and collapsed legacy tools", () => {
    useDashboardDataMock.mockReturnValue(makeDashboardData());
    render(<DashboardPage />);

    expect(screen.getByTestId("continue-mission-hero")).toBeInTheDocument();
    const primaryRow = screen.getByTestId("dashboard-primary-row");
    expect(within(primaryRow).getByTestId("daily-session-cta")).toBeInTheDocument();
    expect(within(primaryRow).getByTestId("learning-paths-pill")).toBeInTheDocument();
    expect(within(primaryRow).getByTestId("drill-courses-pill")).toBeInTheDocument();

    const moreTools = screen.getByTestId("dashboard-more-tools");
    expect(within(moreTools).getByTestId("brutal-drill-cta")).toBeInTheDocument();
    expect(within(moreTools).getByTestId("overview-stats")).toBeInTheDocument();
    expect(screen.getByTestId("course-spaces-section")).toBeInTheDocument();
  });

  it("keeps the empty state when there are no courses", () => {
    useDashboardDataMock.mockReturnValue(
      makeDashboardData({ courses: [], loading: false }),
    );
    render(<DashboardPage />);

    expect(
      screen.queryByTestId("dashboard-primary-row"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("dashboard-empty-state")).toBeInTheDocument();
  });
});
