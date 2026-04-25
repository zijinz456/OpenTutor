import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import DashboardPage from "./page";

const useDashboardDataMock = vi.fn();
const getCurrentMissionMock = vi.fn();

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
  ContinueMissionHero: (props: {
    mission: unknown;
    gate: boolean;
    dueCardCount: number;
  }) => (
    <div
      data-testid="continue-mission-hero"
      data-gate={String(props.gate)}
      data-due={String(props.dueCardCount)}
      data-mission-state={
        props.mission === undefined
          ? "loading"
          : props.mission === null
            ? "empty"
            : "active"
      }
    />
  ),
}));

vi.mock("@/components/dashboard/today-plan-card", () => ({
  TodayPlanCard: (props: {
    totalDueFlashcards: number;
    mission: unknown;
  }) => (
    <div
      data-testid="today-plan-card"
      data-due={String(props.totalDueFlashcards)}
      data-mission-state={
        props.mission === undefined
          ? "loading"
          : props.mission === null
            ? "empty"
            : "active"
      }
    />
  ),
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

vi.mock("@/components/gamification/gamification-widget", () => ({
  GamificationWidget: () => <div data-testid="gamification-widget" />,
}));

vi.mock("@/components/dashboard/brutal-drill-cta", () => ({
  BrutalDrillCTA: () => <div data-testid="brutal-drill-cta" />,
}));

vi.mock("@/components/dashboard/generate-room-cta", () => ({
  GenerateRoomCTA: (props: {
    pathId: string;
    courseId: string;
    pathSlug: string;
  }) => (
    <div
      data-testid="generate-room-cta"
      data-path-id={props.pathId}
      data-course-id={props.courseId}
      data-path-slug={props.pathSlug}
    />
  ),
}));

vi.mock("@/lib/api/paths", () => ({
  getCurrentMission: () => getCurrentMissionMock(),
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
    getCurrentMissionMock.mockReset();
    getCurrentMissionMock.mockResolvedValue(null);
  });

  it("renders the visual shell, hero in main column, and rail with 3 widgets", () => {
    useDashboardDataMock.mockReturnValue(makeDashboardData());
    render(<DashboardPage />);

    // Visual Shell V1 — outer wrapper + above-the-fold grid + support rail.
    const shell = screen.getByTestId("dashboard-shell");
    expect(shell).toBeInTheDocument();

    const grid = screen.getByTestId("dashboard-main-grid");
    expect(grid).toBeInTheDocument();
    expect(shell).toContainElement(grid);

    expect(screen.getByTestId("continue-mission-hero")).toBeInTheDocument();

    const rail = screen.getByTestId("dashboard-support-rail");
    expect(rail).toBeInTheDocument();
    expect(grid).toContainElement(rail);
    expect(within(rail).getByTestId("daily-session-cta")).toBeInTheDocument();
    expect(within(rail).getByTestId("learning-paths-pill")).toBeInTheDocument();
    expect(within(rail).getByTestId("drill-courses-pill")).toBeInTheDocument();
    // Phase 16c Bundle C — passive status widget mounts at the bottom of the rail.
    expect(within(rail).getByTestId("gamification-widget")).toBeInTheDocument();

    // Below-grid sections still mount full-width inside the same shell.
    const moreTools = screen.getByTestId("dashboard-more-tools");
    expect(within(moreTools).getByTestId("brutal-drill-cta")).toBeInTheDocument();
    expect(within(moreTools).getByTestId("overview-stats")).toBeInTheDocument();
    expect(screen.getByTestId("course-spaces-section")).toBeInTheDocument();
  });

  it("mounts TodayPlanCard above ContinueMissionHero in the main column", () => {
    useDashboardDataMock.mockReturnValue(
      makeDashboardData({ totalDueFlashcards: 3 }),
    );
    render(<DashboardPage />);

    const missionFirst = screen.getByTestId("dashboard-mission-first");
    const todayPlan = screen.getByTestId("today-plan-card");
    const hero = screen.getByTestId("continue-mission-hero");

    expect(missionFirst).toContainElement(todayPlan);
    expect(missionFirst).toContainElement(hero);

    // TodayPlanCard must render before the hero in document order.
    const order = todayPlan.compareDocumentPosition(hero);
    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // Page forwards review-gate context to the hero.
    expect(hero).toHaveAttribute("data-gate", "true");
    expect(hero).toHaveAttribute("data-due", "3");
    expect(todayPlan).toHaveAttribute("data-due", "3");
  });

  it("forwards gate=false when no flashcards are due", () => {
    useDashboardDataMock.mockReturnValue(
      makeDashboardData({ totalDueFlashcards: 0 }),
    );
    render(<DashboardPage />);

    const hero = screen.getByTestId("continue-mission-hero");
    expect(hero).toHaveAttribute("data-gate", "false");
    expect(hero).toHaveAttribute("data-due", "0");
  });

  it("keeps the empty state when there are no courses", () => {
    useDashboardDataMock.mockReturnValue(
      makeDashboardData({ courses: [], loading: false }),
    );
    render(<DashboardPage />);

    expect(
      screen.queryByTestId("dashboard-main-grid"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("dashboard-support-rail"),
    ).not.toBeInTheDocument();
    // Shell wrapper still mounts even when there are no courses.
    expect(screen.getByTestId("dashboard-shell")).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-empty-state")).toBeInTheDocument();
  });

  it("mounts GenerateRoomCTA once mission + course context resolve", async () => {
    useDashboardDataMock.mockReturnValue(makeDashboardData());
    getCurrentMissionMock.mockResolvedValue({
      mission_id: "m-1",
      path_id: "path-1",
      path_slug: "python-basics",
      path_title: "Python basics",
      title: "Loops",
      intro_excerpt: null,
      outcome: null,
      difficulty: 1,
      eta_minutes: 10,
      module_label: null,
      task_total: 5,
      task_complete: 1,
      progress_pct: 20,
    });

    render(<DashboardPage />);

    const cta = await waitFor(() => screen.getByTestId("generate-room-cta"));
    expect(cta).toHaveAttribute("data-path-id", "path-1");
    expect(cta).toHaveAttribute("data-course-id", "course-1");
    expect(cta).toHaveAttribute("data-path-slug", "python-basics");
  });

  it("hides GenerateRoomCTA when no mission is available", async () => {
    useDashboardDataMock.mockReturnValue(makeDashboardData());
    getCurrentMissionMock.mockResolvedValue(null);

    render(<DashboardPage />);

    // Allow the effect microtask to flush.
    await Promise.resolve();
    expect(screen.queryByTestId("generate-room-cta")).not.toBeInTheDocument();
  });
});
