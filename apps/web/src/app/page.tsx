"use client";

import { useEffect, useState } from "react";
import { useLocale } from "@/lib/i18n-context";
import { RuntimeAlert } from "@/components/shared/runtime-alert";
import { ContinueMissionHero } from "@/components/dashboard/continue-mission-hero";
import { TodayPlanCard } from "@/components/dashboard/today-plan-card";
import { DailySessionCTA } from "@/components/dashboard/daily-session-cta";
import { BrutalDrillCTA } from "@/components/dashboard/brutal-drill-cta";
import { LearningPathsPill } from "@/components/dashboard/LearningPathsPill";
import { DrillCoursesPill } from "@/components/dashboard/DrillCoursesPill";
import { GamificationWidget } from "@/components/gamification/gamification-widget";
import { LevelRingCard } from "@/components/dashboard/level-ring-card";
import { StreakCard } from "@/components/dashboard/streak-card";
import { HeatmapCard } from "@/components/dashboard/heatmap-card";
import { DailyGoalCard } from "@/components/dashboard/daily-goal-card";
import { WelcomeBackModal } from "@/components/dashboard/welcome-back-modal";
import { GenerateRoomCTA } from "@/components/dashboard/generate-room-cta";
import {
  getCurrentMission,
  type CurrentMissionResponse,
} from "@/lib/api/paths";
import {
  getGamificationDashboard,
  type GamificationDashboard,
} from "@/lib/api/gamification";
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

  // Visual Shell V2 — single mission fetch shared by the hero, the
  // TodayPlanCard, and the GenerateRoomCTA slot. `undefined` while the
  // request is in flight so the hero renders its skeleton; the API
  // resolves to either a mission object or `null`.
  //
  // Phase 16b Bundle B — the GenerateRoomCTA also needs a (path_id,
  // path_slug, course_id) trio. The dashboard payload doesn't expose a
  // course_id mapping yet, so for MVL we hide the CTA unless we can pair
  // the mission's path with a course from the user's dashboard.
  const [currentMission, setCurrentMission] = useState<
    CurrentMissionResponse | undefined
  >(undefined);
  useEffect(() => {
    let cancelled = false;
    getCurrentMission()
      .then((mission) => {
        if (!cancelled) setCurrentMission(mission);
      })
      .catch(() => {
        if (!cancelled) setCurrentMission(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Phase 16c Bundle B — single fetch shared by the 4-card gamification
  // block inside the More-tools details. The legacy <GamificationWidget>
  // in the support rail keeps its own internal fetch (different layout
  // context, different lifecycle) — see spec note. `null` here means we
  // failed to load and fall through to omitting the cards rather than
  // showing an error banner.
  const [gamification, setGamification] = useState<
    GamificationDashboard | null
  >(null);
  useEffect(() => {
    let cancelled = false;
    getGamificationDashboard()
      .then((data) => {
        if (!cancelled) setGamification(data);
      })
      .catch(() => {
        if (!cancelled) setGamification(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const generateCourseId =
    courses.length > 0 ? (courses[0] as { id: string }).id : null;
  const reviewGate = totalDueFlashcards > 0;

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
      {/* Visual Shell V1 — Slice 1 (Dashboard).
          Outer container is the shared shell wrapper agreed with main agent
          + Subagent B: max-w-[1600px] with responsive horizontal padding.
          Above-the-fold = 2-col grid (main + 380px support rail) at xl+.
          Below xl, single column — rail items stack under hero. */}
      <main
        data-testid="dashboard-shell"
        className="mx-auto w-full max-w-[1600px] px-4 md:px-6 xl:px-10 pb-24 pt-8 md:pt-12 flex flex-col gap-6"
      >
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
            data-testid="dashboard-main-grid"
            className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px] gap-6"
          >
            <div
              data-testid="dashboard-mission-first"
              className="space-y-6 min-w-0"
            >
              <TodayPlanCard
                totalDueFlashcards={totalDueFlashcards}
                mission={currentMission}
              />
              <ContinueMissionHero
                mission={currentMission}
                gate={reviewGate}
                dueCardCount={totalDueFlashcards}
              />
              {currentMission && generateCourseId && (
                <div data-testid="dashboard-generate-room-slot">
                  <GenerateRoomCTA
                    pathId={currentMission.path_id}
                    courseId={generateCourseId}
                    pathSlug={currentMission.path_slug}
                  />
                </div>
              )}
            </div>
            <aside
              data-testid="dashboard-support-rail"
              className="space-y-4 min-w-0 xl:sticky xl:top-20 xl:self-start"
            >
              <DailySessionCTA />
              <LearningPathsPill />
              <DrillCoursesPill />
              {/* Phase 16c Bundle C — passive status widget at the
                  bottom of the rail (status, not action). */}
              <GamificationWidget />
            </aside>
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
              {/* Phase 16c Bundle B — 4-card gamification block at the
                  top of More-tools content (per spec C.2). The rail-level
                  <GamificationWidget> stays — it serves a different
                  layout context (always visible, narrow column). */}
              {gamification && (
                <div
                  data-testid="dashboard-gamification-cards"
                  className="grid grid-cols-1 md:grid-cols-2 gap-4"
                >
                  <LevelRingCard
                    xpTotal={gamification.xp_total}
                    levelTier={gamification.level_tier}
                    levelName={gamification.level_name}
                    levelProgressPct={gamification.level_progress_pct}
                    xpToNextLevel={gamification.xp_to_next_level}
                  />
                  <StreakCard
                    streakDays={gamification.streak_days}
                    freezesLeft={gamification.streak_freezes_left}
                  />
                  <HeatmapCard
                    tiles={gamification.heatmap}
                    className="md:col-span-2"
                  />
                  <DailyGoalCard
                    dailyGoalXp={gamification.daily_goal_xp}
                    dailyXpEarned={gamification.daily_xp_earned}
                    className="md:col-span-2"
                  />
                </div>
              )}

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
