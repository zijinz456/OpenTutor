"use client";

import { useLocale } from "@/lib/i18n-context";
import { RuntimeAlert } from "@/components/shared/runtime-alert";
import { useDashboardData } from "./_hooks/use-dashboard-data";
import { CourseCardsSkeleton } from "./_components/dash-section";
import { LearningRhythm } from "./_components/digest-fallback";
import { DashboardSidebar } from "./_components/dashboard-sidebar";
import {
  OverviewStats,
  TodayDigestSection,
  UpcomingDeadlinesSection,
  UrgentReviewsSection,
  KnowledgeDensitySection,
  AgentInsightsSection,
  PendingApprovalsSection,
  ModeRecommendationsSection,
  WeeklyStatsSection,
  MasteryOverviewSection,
} from "./_components/dashboard-sections";
import { CourseSpacesSection, DashboardEmptyState } from "./_components/dashboard-spaces";

export default function DashboardPage() {
  const { locale } = useLocale();
  const {
    router, t, tf, courses, loading, error, health,
    reviewSummaries, notifications, pendingTasks, actingTasks,
    modeRecommendations, actingModeCourses, upcomingDeadlines,
    dailyDigest, knowledgeDensity, weeklyReport, masteryOverview,
    totalActiveGoals, totalPendingApprovals, totalRunningTasks, totalUrgentReviews,
    actOnTask, applyModeRecommendation, dismissModeRecommendation,
  } = useDashboardData();

  const navigate = (path: string) => router.push(path);

  const getDeadlineLabel = (daysUntil: number): string => {
    if (daysUntil <= 0) return t("home.deadline.overdue");
    if (daysUntil === 1) return t("home.deadline.tomorrow");
    return tf("home.deadline.inDays", { days: daysUntil });
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="flex min-h-screen flex-col md:flex-row">
        <DashboardSidebar health={health} t={t} onNavigate={navigate} />

        <main className="flex-1 overflow-y-auto scrollbar-thin">
          <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-8 sm:px-6 md:px-10 md:py-12">
            <RuntimeAlert health={health} />

            {error && (
              <div className="rounded-2xl bg-destructive/5 px-5 py-4 text-sm text-destructive card-shadow">
                {t("dashboard.loadErrorPrefix")}: {error}
              </div>
            )}

            {/* Title + New Space */}
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div className="flex flex-col gap-1.5">
                <h1 className="text-2xl font-bold tracking-tight text-foreground">{t("dashboard.title")}</h1>
                <p className="text-sm text-muted-foreground">{t("dashboard.subtitle")}</p>
              </div>
              <button
                type="button"
                onClick={() => router.push("/new")}
                className="h-10 px-6 bg-brand text-brand-foreground rounded-full text-sm font-medium hover:opacity-90 transition-all hover:shadow-md shrink-0 self-start sm:self-auto"
              >
                + {t("dashboard.create")}
              </button>
            </div>

            {courses.length > 0 && (
              <OverviewStats
                totalActiveGoals={totalActiveGoals}
                totalPendingApprovals={totalPendingApprovals}
                totalRunningTasks={totalRunningTasks}
                t={t}
              />
            )}

            {courses.length > 0 && <WeeklyStatsSection weeklyReport={weeklyReport} />}
            {courses.length > 1 && <MasteryOverviewSection masteryOverview={masteryOverview} onNavigate={navigate} />}

            {courses.length > 0 && (
              <TodayDigestSection
                courses={courses} dailyDigest={dailyDigest}
                reviewSummaries={reviewSummaries} upcomingDeadlines={upcomingDeadlines}
                t={t} tf={tf}
              />
            )}

            {courses.length > 0 && (
              <UpcomingDeadlinesSection
                upcomingDeadlines={upcomingDeadlines}
                getDeadlineLabel={getDeadlineLabel}
                onNavigate={navigate} t={t}
              />
            )}

            {courses.length > 0 && (
              <UrgentReviewsSection
                reviewSummaries={reviewSummaries}
                totalUrgentReviews={totalUrgentReviews}
                onNavigate={navigate} t={t} tf={tf}
              />
            )}

            {courses.length > 1 && (
              <KnowledgeDensitySection knowledgeDensity={knowledgeDensity} t={t} />
            )}

            {courses.length > 0 && (
              <AgentInsightsSection notifications={notifications} onNavigate={navigate} t={t} />
            )}

            {courses.length > 0 && (
              <PendingApprovalsSection
                pendingTasks={pendingTasks} actingTasks={actingTasks}
                onActOnTask={(id, action) => void actOnTask(id, action)}
                t={t} tf={tf}
              />
            )}

            {courses.length > 0 && (
              <ModeRecommendationsSection
                modeRecommendations={modeRecommendations} actingModeCourses={actingModeCourses}
                onApply={(item) => void applyModeRecommendation(item)}
                onDismiss={dismissModeRecommendation}
                onNavigate={navigate} t={t}
              />
            )}

            {courses.length > 0 && <LearningRhythm t={t} />}
            {loading && <CourseCardsSkeleton />}
            {courses.length > 0 && (
              <CourseSpacesSection courses={courses} locale={locale} onNavigate={navigate} t={t} />
            )}
            {!loading && courses.length === 0 && (
              <DashboardEmptyState onNavigate={navigate} t={t} />
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
