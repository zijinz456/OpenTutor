"use client";

import { useLocale } from "@/lib/i18n-context";
import { RuntimeAlert } from "@/components/shared/runtime-alert";
import { ContinueMissionHero } from "@/components/dashboard/continue-mission-hero";
import { DailySessionCTA } from "@/components/dashboard/daily-session-cta";
import { BrutalDrillCTA } from "@/components/dashboard/brutal-drill-cta";
import { LearningPathsPill } from "@/components/dashboard/LearningPathsPill";
import { DrillCoursesPill } from "@/components/dashboard/DrillCoursesPill";
import { WelcomeBackModal } from "@/components/dashboard/welcome-back-modal";
import { useDashboardData } from "./_hooks/use-dashboard-data";
import { CourseCardsSkeleton } from "./_components/dash-section";
import { LearningRhythm } from "./_components/digest-fallback";
import {
  OverviewStats,
  TodayDigestSection,
  UpcomingDeadlinesSection,
  UrgentReviewsSection,
  FlashcardsDueSection,
  KnowledgeDensitySection,
  AgentInsightsSection,
  PendingApprovalsSection,
  ModeRecommendationsSection,
  WeeklyStatsSection,
  MasteryOverviewSection,
} from "./_components/dashboard-sections";
import {
  CourseSpacesSection,
  DashboardEmptyState,
} from "./_components/dashboard-spaces";

export default function DashboardPage() {
  const { locale } = useLocale();
  const {
    router,
    t,
    tf,
    courses,
    loading,
    error,
    health,
    reviewSummaries,
    notifications,
    pendingTasks,
    actingTasks,
    modeRecommendations,
    actingModeCourses,
    upcomingDeadlines,
    dailyDigest,
    knowledgeDensity,
    weeklyReport,
    masteryOverview,
    flashcardDueByCourse,
    totalDueFlashcards,
    totalActiveGoals,
    totalPendingApprovals,
    totalRunningTasks,
    totalUrgentReviews,
    actOnTask,
    applyModeRecommendation,
    dismissModeRecommendation,
  } = useDashboardData();

  const navigate = (path: string) => router.push(path);

  const getDeadlineLabel = (daysUntil: number): string => {
    if (daysUntil <= 0) return t("home.deadline.overdue");
    if (daysUntil === 1) return t("home.deadline.tomorrow");
    return tf("home.deadline.inDays", { days: daysUntil });
  };

  return (
    <div className="min-h-screen bg-background">
      {/* ADHD Phase 14 T4 — welcome-back reminder. Always mounted; the
          component returns `null` when the user has not been away 3+
          days or has already dismissed today. */}
      <WelcomeBackModal />
      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6 md:px-10 md:py-12">
        <RuntimeAlert health={health} />

        {error && (
          <div className="rounded-2xl bg-destructive/5 px-5 py-4 text-sm text-destructive card-shadow">
            {t("dashboard.loadErrorPrefix")}: {error}
          </div>
        )}

        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex flex-col gap-1.5">
            <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
              {t("dashboard.title")}
            </h1>
            <p className="text-sm text-muted-foreground" data-panic-hide>
              {t("dashboard.subtitle")}
            </p>
          </div>
          <button
            type="button"
            onClick={() => router.push("/new")}
            data-panic-hide
            className="h-10 self-start shrink-0 rounded-full bg-brand px-6 text-sm font-medium text-brand-foreground transition-all hover:opacity-90 hover:shadow-md sm:self-auto"
          >
            + {t("dashboard.create")}
          </button>
        </div>

        {courses.length > 0 && (
          <section
            data-testid="dashboard-mission-first"
            className="flex flex-col gap-4"
          >
            <ContinueMissionHero />
            <div
              data-testid="dashboard-primary-row"
              className="grid gap-4 lg:grid-cols-3"
            >
              <DailySessionCTA />
              <LearningPathsPill />
              <DrillCoursesPill />
            </div>
          </section>
        )}

        {courses.length > 0 && (
          <details
            data-testid="dashboard-more-tools"
            className="rounded-2xl border border-border/70 bg-card/60 p-5 card-shadow"
          >
            <summary className="cursor-pointer list-none">
              <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-semibold text-foreground">
                    More tools
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Daily review, brutal drills, and the rest of the dashboard.
                  </p>
                </div>
                <span className="text-xs text-muted-foreground">
                  Open when you want the full board
                </span>
              </div>
            </summary>

            <div className="mt-5 flex flex-col gap-4">
              <BrutalDrillCTA />

              <div data-panic-hide>
                <OverviewStats
                  totalActiveGoals={totalActiveGoals}
                  totalPendingApprovals={totalPendingApprovals}
                  totalRunningTasks={totalRunningTasks}
                  t={t}
                />
              </div>

              <div data-panic-hide>
                <TodayDigestSection
                  courses={courses}
                  dailyDigest={dailyDigest}
                  reviewSummaries={reviewSummaries}
                  upcomingDeadlines={upcomingDeadlines}
                  t={t}
                  tf={tf}
                />
              </div>

              <div data-panic-hide>
                <UpcomingDeadlinesSection
                  upcomingDeadlines={upcomingDeadlines}
                  getDeadlineLabel={getDeadlineLabel}
                  onNavigate={navigate}
                  t={t}
                />
              </div>

              <div data-panic-hide>
                <UrgentReviewsSection
                  reviewSummaries={reviewSummaries}
                  totalUrgentReviews={totalUrgentReviews}
                  onNavigate={navigate}
                  t={t}
                  tf={tf}
                />
              </div>

              <div data-panic-hide>
                <FlashcardsDueSection
                  flashcardDueByCourse={flashcardDueByCourse}
                  totalDueFlashcards={totalDueFlashcards}
                  onNavigate={navigate}
                  t={t}
                  tf={tf}
                />
              </div>

              <div data-panic-hide>
                <WeeklyStatsSection weeklyReport={weeklyReport} />
              </div>

              {courses.length > 1 && (
                <div data-panic-hide>
                  <MasteryOverviewSection
                    masteryOverview={masteryOverview}
                    onNavigate={navigate}
                  />
                </div>
              )}

              {courses.length > 1 && (
                <div data-panic-hide>
                  <KnowledgeDensitySection
                    knowledgeDensity={knowledgeDensity}
                    t={t}
                  />
                </div>
              )}

              <div data-panic-hide>
                <AgentInsightsSection
                  notifications={notifications}
                  onNavigate={navigate}
                  t={t}
                />
              </div>

              <div data-panic-hide>
                <PendingApprovalsSection
                  pendingTasks={pendingTasks}
                  actingTasks={actingTasks}
                  onActOnTask={(id, action) => void actOnTask(id, action)}
                  t={t}
                  tf={tf}
                />
              </div>

              <div data-panic-hide>
                <ModeRecommendationsSection
                  modeRecommendations={modeRecommendations}
                  actingModeCourses={actingModeCourses}
                  onApply={(item) => void applyModeRecommendation(item)}
                  onDismiss={dismissModeRecommendation}
                  onNavigate={navigate}
                  t={t}
                />
              </div>

              <div data-panic-hide>
                <LearningRhythm t={t} />
              </div>
            </div>
          </details>
        )}

        {loading && <CourseCardsSkeleton />}
        {courses.length > 0 && (
          <div data-panic-hide>
            <CourseSpacesSection
              courses={courses}
              locale={locale}
              onNavigate={navigate}
              t={t}
            />
          </div>
        )}
        {!loading && courses.length === 0 && (
          <DashboardEmptyState onNavigate={navigate} t={t} />
        )}
      </main>
    </div>
  );
}
