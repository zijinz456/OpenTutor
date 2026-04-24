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
  FlashcardsDueSection,
  KnowledgeDensitySection,
  AgentInsightsSection,
  PendingApprovalsSection,
  ModeRecommendationsSection,
  WeeklyStatsSection,
  MasteryOverviewSection,
} from "./_components/dashboard-sections";
import { CourseSpacesSection, DashboardEmptyState } from "./_components/dashboard-spaces";
import { DailySessionCTA } from "@/components/dashboard/daily-session-cta";
import { BrutalDrillCTA } from "@/components/dashboard/brutal-drill-cta";
import { LearningPathsPill } from "@/components/dashboard/LearningPathsPill";
import { WelcomeBackModal } from "@/components/dashboard/welcome-back-modal";
import { PanicToggle } from "@/components/panic/PanicToggle";

export default function DashboardPage() {
  const { locale } = useLocale();
  const {
    router, t, tf, courses, loading, error, health,
    reviewSummaries, notifications, pendingTasks, actingTasks,
    modeRecommendations, actingModeCourses, upcomingDeadlines,
    dailyDigest, knowledgeDensity, weeklyReport, masteryOverview,
    flashcardDueByCourse, totalDueFlashcards,
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
      {/* ADHD Phase 14 T4 — welcome-back reminder. Always mounted; the
          component returns `null` when the user has not been away 3+
          days or has already dismissed today. */}
      <WelcomeBackModal />
      <div className="flex min-h-screen flex-col md:flex-row">
        <div data-panic-hide>
          <DashboardSidebar health={health} t={t} onNavigate={navigate} />
        </div>

        <main className="flex-1 overflow-y-auto scrollbar-thin">
          <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6 md:px-10 md:py-12">
            <RuntimeAlert health={health} />

            {error && (
              <div className="rounded-2xl bg-destructive/5 px-5 py-4 text-sm text-destructive card-shadow">
                {t("dashboard.loadErrorPrefix")}: {error}
              </div>
            )}

            {/* Title + Panic toggle + New Space.
                PanicToggle sits in the header so it's reachable from any
                dashboard state. When Panic Mode is on, <PanicOverlay>
                hides every `data-panic-hide` section below, leaving only
                the title, the toggle itself, and the primary drill CTAs
                visible. */}
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div className="flex flex-col gap-1.5">
                <h1 className="text-2xl font-bold tracking-tight text-foreground">{t("dashboard.title")}</h1>
                <p className="text-sm text-muted-foreground" data-panic-hide>{t("dashboard.subtitle")}</p>
              </div>
              <div className="flex items-center gap-3">
                <PanicToggle />
                <button
                  type="button"
                  onClick={() => router.push("/new")}
                  data-panic-hide
                  className="h-10 px-6 bg-brand text-brand-foreground rounded-full text-sm font-medium hover:opacity-90 transition-all hover:shadow-md shrink-0 self-start sm:self-auto"
                >
                  + {t("dashboard.create")}
                </button>
              </div>
            </div>

            {courses.length > 0 && (
              <div data-panic-hide>
                <OverviewStats
                  totalActiveGoals={totalActiveGoals}
                  totalPendingApprovals={totalPendingApprovals}
                  totalRunningTasks={totalRunningTasks}
                  t={t}
                />
              </div>
            )}

            {courses.length > 0 && <div data-panic-hide><WeeklyStatsSection weeklyReport={weeklyReport} /></div>}
            {courses.length > 1 && <div data-panic-hide><MasteryOverviewSection masteryOverview={masteryOverview} onNavigate={navigate} /></div>}

            {courses.length > 0 && (
              <div data-panic-hide>
                <TodayDigestSection
                  courses={courses} dailyDigest={dailyDigest}
                  reviewSummaries={reviewSummaries} upcomingDeadlines={upcomingDeadlines}
                  t={t} tf={tf}
                />
              </div>
            )}

            {courses.length > 0 && (
              <div data-panic-hide>
                <UpcomingDeadlinesSection
                  upcomingDeadlines={upcomingDeadlines}
                  getDeadlineLabel={getDeadlineLabel}
                  onNavigate={navigate} t={t}
                />
              </div>
            )}

            {/*
              ADHD daily-session entry point (Phase 13). Sits ABOVE
              UrgentReviews per Juri's Q1 decision — not replacing it, so
              overdue visibility is preserved for users who want it. When
              no courses are loaded yet, we skip the CTA along with the
              rest of the dashboard stack to avoid an orphaned button.
            */}
            {courses.length > 0 && <DailySessionCTA />}

            {/*
              Brutal Drill entry (Phase 6). Sits directly below the
              ADHD daily CTA — amber/yellow treatment flags the opt-in
              "interview-prep night" posture without reading as an error
              alert the way red would.
            */}
            {courses.length > 0 && <BrutalDrillCTA />}

            {/* Phase 16a T4 — Python learning paths entry. Honours
                `data-panic-hide` internally so the pill hides with the
                rest of the dashboard when Panic Mode is on. */}
            {courses.length > 0 && <LearningPathsPill />}

            {courses.length > 0 && (
              <div data-panic-hide>
                <UrgentReviewsSection
                  reviewSummaries={reviewSummaries}
                  totalUrgentReviews={totalUrgentReviews}
                  onNavigate={navigate} t={t} tf={tf}
                />
              </div>
            )}

            {courses.length > 0 && (
              <div data-panic-hide>
                <FlashcardsDueSection
                  flashcardDueByCourse={flashcardDueByCourse}
                  totalDueFlashcards={totalDueFlashcards}
                  onNavigate={navigate} t={t} tf={tf}
                />
              </div>
            )}

            {courses.length > 1 && (
              <div data-panic-hide>
                <KnowledgeDensitySection knowledgeDensity={knowledgeDensity} t={t} />
              </div>
            )}

            {courses.length > 0 && (
              <div data-panic-hide>
                <AgentInsightsSection notifications={notifications} onNavigate={navigate} t={t} />
              </div>
            )}

            {courses.length > 0 && (
              <div data-panic-hide>
                <PendingApprovalsSection
                  pendingTasks={pendingTasks} actingTasks={actingTasks}
                  onActOnTask={(id, action) => void actOnTask(id, action)}
                  t={t} tf={tf}
                />
              </div>
            )}

            {courses.length > 0 && (
              <div data-panic-hide>
                <ModeRecommendationsSection
                  modeRecommendations={modeRecommendations} actingModeCourses={actingModeCourses}
                  onApply={(item) => void applyModeRecommendation(item)}
                  onDismiss={dismissModeRecommendation}
                  onNavigate={navigate} t={t}
                />
              </div>
            )}

            {courses.length > 0 && <div data-panic-hide><LearningRhythm t={t} /></div>}
            {loading && <CourseCardsSkeleton />}
            {courses.length > 0 && (
              <div data-panic-hide>
                <CourseSpacesSection courses={courses} locale={locale} onNavigate={navigate} t={t} />
              </div>
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
