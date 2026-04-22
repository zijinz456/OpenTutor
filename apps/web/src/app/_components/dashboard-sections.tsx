"use client";

import {
  Sparkles,
  RotateCcw,
  CalendarDays,
  GitBranch,
  ArrowRight,
  Sun,
  TrendingUp,
  BookOpen,
} from "lucide-react";
import type { Course, AppNotification, StudyGoal, WeeklyReport, LearningOverview } from "@/lib/api";
import { ModeBadge } from "@/components/course/mode-selector";
import { Button } from "@/components/ui/button";
import { DashSection } from "./dash-section";
import { DigestFallback } from "./digest-fallback";
import {
  formatDate,
  getDashboardNowMs,
  resolveNotificationPath,
  type ReviewSummary,
  type PendingTaskSummary,
  type KnowledgeDensitySummary,
  type ModeRecommendation,
} from "./dashboard-utils";

export function OverviewStats({
  totalActiveGoals,
  totalPendingApprovals,
  totalRunningTasks,
  t,
}: {
  totalActiveGoals: number;
  totalPendingApprovals: number;
  totalRunningTasks: number;
  t: (key: string) => string;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <div className="rounded-2xl bg-card p-5 card-shadow">
        <div className="text-xs text-muted-foreground mb-1.5">{t("dashboard.activeGoals")}</div>
        <div className="text-2xl font-bold text-foreground tabular-nums">{totalActiveGoals}</div>
      </div>
      <div className="rounded-2xl bg-card p-5 card-shadow">
        <div className="text-xs text-muted-foreground mb-1.5">{t("dashboard.pendingApprovals")}</div>
        <div className="text-2xl font-bold text-foreground tabular-nums">{totalPendingApprovals}</div>
      </div>
      <div className="rounded-2xl bg-card p-5 card-shadow">
        <div className="text-xs text-muted-foreground mb-1.5">{t("dashboard.runningTasks")}</div>
        <div className="text-2xl font-bold text-foreground tabular-nums">{totalRunningTasks}</div>
      </div>
    </div>
  );
}

export function TodayDigestSection({
  courses,
  dailyDigest,
  reviewSummaries,
  upcomingDeadlines,
  t,
  tf,
}: {
  courses: Course[];
  dailyDigest: AppNotification | null;
  reviewSummaries: ReviewSummary[];
  upcomingDeadlines: Array<{ title: string; target_date: string | null }>;
  t: (key: string) => string;
  tf: (key: string, vars?: Record<string, string | number | null | undefined>) => string;
}) {
  return (
    <DashSection title={t("home.todayDigest")} icon={Sun}>
      {dailyDigest ? (
        <div className="space-y-2">
          <p className="text-sm font-medium text-foreground">{dailyDigest.title}</p>
          <p className="text-sm text-muted-foreground whitespace-pre-line">{dailyDigest.body}</p>
        </div>
      ) : (
        <DigestFallback courses={courses} reviewSummaries={reviewSummaries} upcomingDeadlines={upcomingDeadlines} t={t} tf={tf} />
      )}
    </DashSection>
  );
}

export function UpcomingDeadlinesSection({
  upcomingDeadlines,
  getDeadlineLabel,
  onNavigate,
  t,
}: {
  upcomingDeadlines: Array<StudyGoal & { courseName: string }>;
  getDeadlineLabel: (daysUntil: number) => string;
  onNavigate: (path: string) => void;
  t: (key: string) => string;
}) {
  // LearnDopamine UX pass: auto-hide when empty (avoid "No X" filler)
  if (upcomingDeadlines.length === 0) return null;
  return (
    <DashSection title={t("home.upcomingDeadlines")} icon={CalendarDays} badge={upcomingDeadlines.length}>
      {upcomingDeadlines.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("home.upcomingDeadlines.empty")}</p>
      ) : (
        <div className="space-y-2">
          {upcomingDeadlines.map((d) => {
            const daysUntil = Math.ceil((new Date(d.target_date!).getTime() - getDashboardNowMs()) / (1000 * 60 * 60 * 24));
            const urgencyClass = daysUntil <= 0 ? "text-destructive font-semibold" : daysUntil <= 3 ? "text-warning font-medium" : "text-muted-foreground";
            return (
              <button key={d.id} type="button" onClick={() => d.course_id && onNavigate(`/course/${d.course_id}/plan`)} className="w-full flex items-center gap-3 rounded-xl bg-muted/30 p-3.5 text-left hover:bg-muted/50 transition-colors">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">{d.title}</p>
                  <p className="text-xs text-muted-foreground truncate">{d.courseName}</p>
                </div>
                <span className={`text-xs shrink-0 ${urgencyClass}`}>{getDeadlineLabel(daysUntil)}</span>
              </button>
            );
          })}
        </div>
      )}
    </DashSection>
  );
}

export function UrgentReviewsSection({
  reviewSummaries,
  totalUrgentReviews,
  onNavigate,
  t,
  tf,
}: {
  reviewSummaries: ReviewSummary[];
  totalUrgentReviews: number;
  onNavigate: (path: string) => void;
  t: (key: string) => string;
  tf: (key: string, vars?: Record<string, string | number | null | undefined>) => string;
}) {
  // LearnDopamine UX pass: auto-hide when empty
  if (reviewSummaries.length === 0) return null;
  return (
    <DashSection title={t("home.urgentReviews")} icon={RotateCcw} badge={totalUrgentReviews}>
      {reviewSummaries.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("home.urgentReviews.empty")}</p>
      ) : (
        <div className="space-y-2">
          {reviewSummaries.map((rs) => (
            <button key={rs.courseId} type="button" onClick={() => onNavigate(`/course/${rs.courseId}/review`)} className="w-full flex items-center gap-3 rounded-xl bg-muted/30 p-3.5 text-left hover:bg-muted/50 transition-colors">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-foreground truncate">{rs.courseName}</p>
                <p className="text-xs text-muted-foreground">
                  {rs.overdueCount > 0 && <span className="text-destructive font-medium">{tf("home.reviews.overdue", { count: rs.overdueCount })}</span>}
                  {rs.overdueCount > 0 && rs.urgentCount > 0 && " · "}
                  {rs.urgentCount > 0 && <span className="text-warning font-medium">{tf("home.reviews.urgent", { count: rs.urgentCount })}</span>}
                  {" · "}{tf("home.reviews.total", { count: rs.totalCount })}
                </p>
              </div>
              <ArrowRight className="size-4 text-muted-foreground shrink-0" />
            </button>
          ))}
        </div>
      )}
    </DashSection>
  );
}

// LearnDopamine: SRS flashcard due-count aggregated across courses.
// Distinct from UrgentReviewsSection which shows concept-level review.
export function FlashcardsDueSection({
  flashcardDueByCourse,
  totalDueFlashcards,
  onNavigate,
  t,
  tf,
}: {
  flashcardDueByCourse: Array<{ courseId: string; courseName: string; dueCount: number }>;
  totalDueFlashcards: number;
  onNavigate: (path: string) => void;
  t: (key: string) => string;
  tf: (key: string, vars?: Record<string, string | number | null | undefined>) => string;
}) {
  if (flashcardDueByCourse.length === 0) return null;
  return (
    <DashSection title="Flashcards due" icon={RotateCcw} badge={totalDueFlashcards}>
      <div className="space-y-2">
        {flashcardDueByCourse.map((fc) => (
          <button
            key={fc.courseId}
            type="button"
            onClick={() => onNavigate(`/course/${fc.courseId}/practice`)}
            className="w-full flex items-center gap-3 rounded-xl bg-muted/30 p-3.5 text-left hover:bg-muted/50 transition-colors"
          >
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-foreground truncate">{fc.courseName}</p>
              <p className="text-xs text-muted-foreground">
                <span className="text-warning font-medium">
                  {`${fc.dueCount} card${fc.dueCount === 1 ? "" : "s"} due`}
                </span>
              </p>
            </div>
            <ArrowRight className="size-4 text-muted-foreground shrink-0" />
          </button>
        ))}
      </div>
    </DashSection>
  );
}

export function KnowledgeDensitySection({
  knowledgeDensity,
  t,
}: {
  knowledgeDensity: KnowledgeDensitySummary | null;
  t: (key: string) => string;
}) {
  return (
    <DashSection title={t("home.knowledgeDensity")} icon={GitBranch}>
      {!knowledgeDensity || knowledgeDensity.totalConcepts === 0 ? (
        <p className="text-sm text-muted-foreground">{t("home.knowledgeDensity.empty")}</p>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-xl bg-muted/30 p-3.5">
              <p className="text-[11px] text-muted-foreground">{t("home.knowledgeDensity.shared")}</p>
              <p className="text-base font-semibold text-foreground">{knowledgeDensity.sharedConcepts}</p>
            </div>
            <div className="rounded-xl bg-muted/30 p-3.5">
              <p className="text-[11px] text-muted-foreground">{t("home.knowledgeDensity.total")}</p>
              <p className="text-base font-semibold text-foreground">{knowledgeDensity.totalConcepts}</p>
            </div>
            <div className="rounded-xl bg-muted/30 p-3.5">
              <p className="text-[11px] text-muted-foreground">{t("home.knowledgeDensity.overlap")}</p>
              <p className="text-base font-semibold text-brand">{knowledgeDensity.densityPct}%</p>
            </div>
          </div>
          <div className="h-2.5 rounded-full bg-muted/60 overflow-hidden">
            <div className="h-full bg-brand rounded-full transition-all duration-500" style={{ width: `${knowledgeDensity.densityPct}%` }} />
          </div>
          {knowledgeDensity.topSharedConcepts.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {knowledgeDensity.topSharedConcepts.map((name) => (
                <span key={name} className="text-[11px] px-2 py-0.5 rounded-full bg-brand-muted text-brand">{name}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </DashSection>
  );
}

export function AgentInsightsSection({
  notifications,
  onNavigate,
  t,
}: {
  notifications: AppNotification[];
  onNavigate: (path: string) => void;
  t: (key: string) => string;
}) {
  return (
    <DashSection title={t("home.agentInsights")} icon={Sparkles} badge={notifications.length}>
      {notifications.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("home.agentInsights.empty")}</p>
      ) : (
        <div className="space-y-2">
          {notifications.map((n) => {
            const path = resolveNotificationPath(n);
            const coursePath = n.course_id ? `/course/${n.course_id}` : null;
            const ctaPath = path ?? coursePath;
            const ctaLabel = n.action_label || t("home.agentInsights.open");
            return (
              <div key={n.id} className="flex items-start gap-3 rounded-xl bg-muted/30 p-3.5">
                <Sparkles className="size-4 text-brand shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground">{n.title}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{n.body}</p>
                  {ctaPath && (
                    <button type="button" onClick={() => onNavigate(ctaPath)} className="mt-1.5 text-[11px] font-medium text-brand hover:underline">
                      {ctaLabel}
                    </button>
                  )}
                </div>
                <span className="text-[10px] text-muted-foreground shrink-0">{formatDate(n.created_at)}</span>
              </div>
            );
          })}
        </div>
      )}
    </DashSection>
  );
}

export function PendingApprovalsSection({
  pendingTasks,
  actingTasks,
  onActOnTask,
  t,
  tf,
}: {
  pendingTasks: PendingTaskSummary[];
  actingTasks: Set<string>;
  onActOnTask: (taskId: string, action: "approve" | "reject") => void;
  t: (key: string) => string;
  tf: (key: string, vars?: Record<string, string | number | null | undefined>) => string;
}) {
  return (
    <DashSection title={t("home.pendingApprovals.title")} icon={Sparkles} badge={pendingTasks.length}>
      {pendingTasks.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("home.pendingApprovals.empty")}</p>
      ) : (
        <div className="space-y-2">
          {pendingTasks.map((task) => (
            <div key={task.id} className="rounded-xl bg-muted/30 p-3.5">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-foreground">{task.title}</p>
                  {task.summary && <p className="text-xs text-muted-foreground mt-0.5">{task.summary}</p>}
                  <p className="text-[11px] text-muted-foreground mt-1">
                    {task.courseName || t("home.pendingApprovals.courseUnknown")} · {tf("home.pendingApprovals.source", { taskType: task.task_type, source: task.source })}
                  </p>
                  {task.approval_reason && <p className="text-[11px] text-muted-foreground mt-1">{t("home.pendingApprovals.reason")} {task.approval_reason}</p>}
                </div>
                <div className="flex shrink-0 gap-1.5">
                  <Button size="sm" variant="outline" disabled={actingTasks.has(task.id)} onClick={() => onActOnTask(task.id, "reject")}>{t("home.pendingApprovals.reject")}</Button>
                  <Button size="sm" disabled={actingTasks.has(task.id)} onClick={() => onActOnTask(task.id, "approve")}>{t("home.pendingApprovals.approve")}</Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </DashSection>
  );
}

export function WeeklyStatsSection({ weeklyReport }: { weeklyReport: WeeklyReport | null }) {
  if (!weeklyReport) return null;
  const { this_week, last_week, deltas } = weeklyReport;

  const delta = (val: number, unit: string) => {
    if (val === 0) return null;
    const sign = val > 0 ? "+" : "";
    return (
      <span className={`text-[10px] font-medium ${val > 0 ? "text-success" : "text-destructive"}`}>
        {sign}{val}{unit}
      </span>
    );
  };

  return (
    <DashSection title="This week" icon={TrendingUp}>
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-xl bg-muted/30 p-3.5 flex flex-col gap-1">
          <p className="text-[11px] text-muted-foreground">Study time</p>
          <p className="text-lg font-bold text-foreground tabular-nums">{this_week.study_minutes}<span className="text-xs font-normal text-muted-foreground ml-0.5">min</span></p>
          {delta(deltas.study_minutes, "min")}
          <p className="text-[10px] text-muted-foreground">Last week: {last_week.study_minutes} min</p>
        </div>
        <div className="rounded-xl bg-muted/30 p-3.5 flex flex-col gap-1">
          <p className="text-[11px] text-muted-foreground">Quiz accuracy</p>
          <p className="text-lg font-bold text-foreground tabular-nums">{this_week.accuracy}<span className="text-xs font-normal text-muted-foreground ml-0.5">%</span></p>
          {delta(deltas.accuracy, "%")}
          <p className="text-[10px] text-muted-foreground">Last week: {last_week.accuracy}%</p>
        </div>
        <div className="rounded-xl bg-muted/30 p-3.5 flex flex-col gap-1">
          <p className="text-[11px] text-muted-foreground">Active days</p>
          <p className="text-lg font-bold text-foreground tabular-nums">{this_week.active_days}<span className="text-xs font-normal text-muted-foreground ml-0.5">d</span></p>
          <p className="text-[10px] text-muted-foreground">Last week: {last_week.active_days} d</p>
        </div>
      </div>
      {weeklyReport.highlights.length > 0 && (
        <div className="mt-3 space-y-1">
          {weeklyReport.highlights.map((h, i) => (
            <p key={i} className="text-xs text-muted-foreground flex items-center gap-1.5">
              <span className="size-1 rounded-full bg-brand shrink-0" />
              {h}
            </p>
          ))}
        </div>
      )}
    </DashSection>
  );
}

export function MasteryOverviewSection({
  masteryOverview,
  onNavigate,
}: {
  masteryOverview: LearningOverview | null;
  onNavigate: (path: string) => void;
}) {
  if (!masteryOverview || masteryOverview.course_summaries.length === 0) return null;

  return (
    <DashSection title="Mastery across courses" icon={BookOpen}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl bg-muted/30 p-3.5">
            <p className="text-[11px] text-muted-foreground">Average mastery</p>
            <p className="text-xl font-bold text-brand tabular-nums">
              {Math.round(masteryOverview.average_mastery * 100)}%
            </p>
          </div>
          <div className="rounded-xl bg-muted/30 p-3.5">
            <p className="text-[11px] text-muted-foreground">Total study time</p>
            <p className="text-xl font-bold text-foreground tabular-nums">
              {masteryOverview.total_study_minutes}<span className="text-xs font-normal text-muted-foreground ml-0.5">min</span>
            </p>
          </div>
        </div>
        <div className="space-y-2">
          {masteryOverview.course_summaries.slice(0, 4).map((c) => (
            <button
              key={c.course_id}
              type="button"
              onClick={() => onNavigate(`/course/${c.course_id}/profile`)}
              className="w-full flex items-center gap-3 rounded-xl bg-muted/20 p-3 hover:bg-muted/40 transition-colors text-left"
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-foreground truncate">{c.course_name}</p>
                <div className="mt-1 h-1.5 rounded-full bg-muted/60 overflow-hidden">
                  <div
                    className="h-full bg-brand rounded-full transition-all duration-500"
                    style={{ width: `${Math.round(c.average_mastery * 100)}%` }}
                  />
                </div>
              </div>
              <span className="text-sm font-semibold text-brand tabular-nums shrink-0">
                {Math.round(c.average_mastery * 100)}%
              </span>
            </button>
          ))}
        </div>
      </div>
    </DashSection>
  );
}

export function ModeRecommendationsSection({
  modeRecommendations,
  actingModeCourses,
  onApply,
  onDismiss,
  onNavigate,
  t,
}: {
  modeRecommendations: ModeRecommendation[];
  actingModeCourses: Set<string>;
  onApply: (item: ModeRecommendation) => void;
  onDismiss: (item: ModeRecommendation) => void;
  onNavigate: (path: string) => void;
  t: (key: string) => string;
}) {
  return (
    <DashSection title={t("home.modeRecommendations.title")} icon={Sparkles} badge={modeRecommendations.length}>
      {modeRecommendations.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("home.modeRecommendations.empty")}</p>
      ) : (
        <div className="space-y-2">
          {modeRecommendations.map((item) => (
            <div key={item.courseId} className="rounded-xl bg-muted/30 p-3.5">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-foreground">{item.courseName}</p>
                  <div className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <span>{t("home.modeRecommendations.current")}</span>
                    <ModeBadge mode={item.currentMode} />
                    <ArrowRight className="size-3.5" />
                    <ModeBadge mode={item.suggestedMode} />
                  </div>
                  <p className="text-xs text-muted-foreground mt-1.5">{item.reason}</p>
                  {item.signals.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {item.signals.map((signal) => (
                        <span key={`${item.courseId}-${signal}`} className="inline-flex rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">{signal}</span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex shrink-0 gap-1.5">
                  <Button size="sm" variant="outline" disabled={actingModeCourses.has(item.courseId)} onClick={() => onDismiss(item)}>{t("home.modeRecommendations.snooze")}</Button>
                  <Button size="sm" variant="outline" onClick={() => onNavigate(`/course/${item.courseId}`)}>{t("home.modeRecommendations.openCourse")}</Button>
                  <Button size="sm" disabled={actingModeCourses.has(item.courseId)} onClick={() => onApply(item)}>{t("home.modeRecommendations.apply")}</Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </DashSection>
  );
}

