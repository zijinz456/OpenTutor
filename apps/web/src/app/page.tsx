"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useCourseStore } from "@/store/course";
import {
  getHealthStatus,
  getCourseProgress,
  updateCourseLayout,
  getKnowledgeGraph,
  getReviewSession,
  listAgentTasks,
  approveAgentTask,
  rejectAgentTask,
  logAgentDecision,
  markTaskNotificationsRead,
  listNotifications,
  type HealthStatus,
  type Course,
  type AppNotification,
  type AgentTask,
} from "@/lib/api";
import { listStudyGoals, type StudyGoal } from "@/lib/api/progress";
import { ttlCache } from "@/lib/cache";
import { useLocale, useT, useTF } from "@/lib/i18n-context";
import { RuntimeAlert } from "@/components/shared/runtime-alert";
import { ModeBadge } from "@/components/course/mode-selector";
import { Button } from "@/components/ui/button";
import type { LearningMode, SpaceLayout } from "@/lib/block-system/types";
import { buildLayoutFromMode } from "@/lib/block-system/templates";
import { updateUnlockContext } from "@/lib/block-system/feature-unlock";
import { getPersona, getOptimalStudyWindows, formatStudyWindow } from "@/lib/learner-persona";
import { initStudyNotifications } from "@/lib/study-notifications";
import {
  Sparkles,
  RotateCcw,
  CalendarDays,
  BookOpen,
  GitBranch,
  ArrowRight,
  Settings,
  Clock,
  Sun,
} from "lucide-react";

const CARD_COLORS = [
  { bg: "bg-brand-muted", text: "text-brand" },
  { bg: "bg-success-muted", text: "text-success" },
  { bg: "bg-warning-muted", text: "text-warning" },
  { bg: "bg-info-muted", text: "text-info" },
];
function getDashboardNowMs() { return Date.now(); }
const MODE_REC_SNOOZE_MS = 12 * 60 * 60 * 1000;

function getInitials(name: string) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || "")
    .join("");
}

function formatDate(value?: string | null) {
  if (!value) return null;
  return new Date(value).toLocaleDateString();
}

function resolveNotificationPath(notification: AppNotification): string | null {
  const actionUrl = notification.action_url?.trim();
  if (actionUrl?.startsWith("/")) return actionUrl;
  const data = notification.data;
  if (!data || typeof data !== "object") return null;
  const candidate = (data as Record<string, unknown>).action_url;
  if (typeof candidate === "string" && candidate.trim().startsWith("/")) {
    return candidate.trim();
  }
  return null;
}

function notificationMatchesTask(notification: AppNotification, taskId: string): boolean {
  const data = notification.data;
  if (!data || typeof data !== "object") return false;
  const record = data as Record<string, unknown>;
  return record.task_id === taskId ||
    record.queued_task_id === taskId ||
    record.agent_task_id === taskId;
}

function getCourseMode(course: Course): LearningMode | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const raw = localStorage.getItem(`opentutor_blocks_${course.id}`);
    if (raw) {
      const layout = JSON.parse(raw) as SpaceLayout;
      if (layout.mode) return layout.mode;
    }
  } catch {
    // Ignore local parse failures and fall back to server metadata.
  }
  const metadata = (course.metadata ?? {}) as Record<string, unknown>;
  const layout = metadata.spaceLayout as SpaceLayout | undefined;
  const mode = layout?.mode ?? metadata.learning_mode;
  return typeof mode === "string" ? (mode as LearningMode) : undefined;
}

interface ReviewSummary {
  courseId: string;
  courseName: string;
  overdueCount: number;
  urgentCount: number;
  totalCount: number;
}

type PendingTaskSummary = AgentTask & { courseName: string };

interface KnowledgeDensitySummary {
  totalConcepts: number;
  sharedConcepts: number;
  densityPct: number;
  topSharedConcepts: string[];
}

interface ModeRecommendation {
  courseId: string;
  courseName: string;
  currentMode: LearningMode;
  suggestedMode: LearningMode;
  recommendationKey: string;
  reason: string;
  signals: string[];
}

function modeRecSnoozeStorageKey(courseId: string, recommendationKey: string): string {
  return `opentutor_home_mode_rec_snooze_${courseId}_${recommendationKey}`;
}

function isModeRecommendationSnoozed(courseId: string, recommendationKey: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    const raw = localStorage.getItem(modeRecSnoozeStorageKey(courseId, recommendationKey));
    if (!raw) return false;
    const ts = Number(raw);
    if (Number.isNaN(ts)) return false;
    return Date.now() - ts < MODE_REC_SNOOZE_MS;
  } catch {
    return false;
  }
}

function snoozeModeRecommendation(courseId: string, recommendationKey: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(modeRecSnoozeStorageKey(courseId, recommendationKey), String(Date.now()));
  } catch {
    // ignore storage failures
  }
}

function normalizeConceptLabel(label: string): string {
  return label.trim().toLowerCase().replace(/\s+/g, " ");
}

function CourseCardsSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="p-5 rounded-2xl flex flex-col gap-3 animate-pulse bg-card card-shadow">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-muted rounded-xl" />
            <div className="flex flex-col gap-1.5 flex-1">
              <div className="h-4 bg-muted rounded-lg w-3/4" />
              <div className="h-3 bg-muted rounded-lg w-1/2" />
            </div>
          </div>
          <div className="h-3 bg-muted rounded-lg w-2/3" />
        </div>
      ))}
    </div>
  );
}

/** Collapsible card section. */
function DashSection({
  title,
  icon: Icon,
  children,
  badge,
}: {
  title: string;
  icon: typeof Sparkles;
  children: React.ReactNode;
  badge?: number;
}) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <section className="rounded-2xl bg-card card-shadow overflow-hidden animate-slide-up">
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="w-full flex items-center gap-2.5 px-5 py-3.5 text-left hover:bg-muted/30 transition-colors"
      >
        <div className="size-7 rounded-lg bg-brand-muted flex items-center justify-center shrink-0">
          <Icon className="size-3.5 text-brand" />
        </div>
        <span className="text-sm font-semibold text-foreground flex-1">{title}</span>
        {badge != null && badge > 0 && (
          <span className="text-[11px] font-medium bg-brand-muted text-brand px-2.5 py-0.5 rounded-full tabular-nums">
            {badge}
          </span>
        )}
        <span className={`text-muted-foreground transition-transform duration-200 ${collapsed ? "" : "rotate-180"}`}>
          <svg className="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path d="M19 9l-7 7-7-7" />
          </svg>
        </span>
      </button>
      <div
        className={`grid transition-all duration-300 ease-out ${collapsed ? "grid-rows-[0fr]" : "grid-rows-[1fr]"}`}
      >
        <div className="overflow-hidden">
          <div className="px-5 pb-5">{children}</div>
        </div>
      </div>
    </section>
  );
}

/** Client-side digest fallback when backend daily_brief is not available. */
function DigestFallback({
  courses,
  reviewSummaries,
  upcomingDeadlines,
  t,
  tf,
}: {
  courses: Course[];
  reviewSummaries: ReviewSummary[];
  upcomingDeadlines: Array<{ title: string; target_date: string | null }>;
  t: (key: string) => string;
  tf: (key: string, vars?: Record<string, string | number | null | undefined>) => string;
}) {
  const persona = getPersona();
  if (persona.totalSessions === 0) {
    return <p className="text-sm text-muted-foreground">{t("home.todayDigest.empty")}</p>;
  }

  const totalReviewItems = reviewSummaries.reduce((s, r) => s + r.overdueCount + r.urgentCount, 0);
  const nextDeadline = upcomingDeadlines[0];
  const daysUntilDeadline = nextDeadline?.target_date
    ? Math.ceil((new Date(nextDeadline.target_date).getTime() - getDashboardNowMs()) / (1000 * 60 * 60 * 24))
    : null;

  return (
    <div className="space-y-1.5 text-sm text-muted-foreground">
      <p>
        <span className="text-foreground font-medium">{courses.length}</span>{" "}
        {courses.length === 1 ? t("home.digest.activeSpace") : t("home.digest.activeSpaces")} ·{" "}
        {tf("home.digest.sessionsTracked", { count: persona.totalSessions })}
      </p>
      {totalReviewItems > 0 && (
        <p>
          <span className="text-warning font-medium">{totalReviewItems}</span>{" "}
          {t("home.urgentReviews.conceptsFading")}
        </p>
      )}
      {daysUntilDeadline != null && daysUntilDeadline >= 0 && (
        <p>
          {t("home.digest.nextDeadline")} <span className="text-foreground font-medium">{nextDeadline!.title}</span>{" "}
          {tf("home.digest.inDays", { days: daysUntilDeadline })}
        </p>
      )}
    </div>
  );
}

/** Learning rhythm visualization from Learner's Persona data. */
function LearningRhythm({ t }: { t: (key: string) => string }) {
  const persona = getPersona();
  const windows = getOptimalStudyWindows();

  if (persona.totalSessions < 3) return null;

  const dayLabels = ["S", "M", "T", "W", "T", "F", "S"];
  // Build a 7×24 heatmap (simplified to 7×4 time blocks: morning, afternoon, evening, night)
  const timeBlocks = [
    { label: "AM", hours: [6, 7, 8, 9, 10, 11] },
    { label: "PM", hours: [12, 13, 14, 15, 16, 17] },
    { label: "Eve", hours: [18, 19, 20, 21, 22, 23] },
    { label: "Night", hours: [0, 1, 2, 3, 4, 5] },
  ];

  // Aggregate counts per day+timeblock
  const heatmap: number[][] = Array.from({ length: 7 }, () => [0, 0, 0, 0]);
  let maxCount = 1;
  for (const slot of persona.studyTimes) {
    const blockIdx = timeBlocks.findIndex((b) => b.hours.includes(slot.hour));
    if (blockIdx >= 0 && slot.dayOfWeek >= 0 && slot.dayOfWeek < 7) {
      heatmap[slot.dayOfWeek][blockIdx] += slot.count;
      maxCount = Math.max(maxCount, heatmap[slot.dayOfWeek][blockIdx]);
    }
  }

  return (
    <DashSection title={t("home.studyRhythm")} icon={Clock}>
      <div className="space-y-3">
        {/* Heatmap grid */}
        <div className="flex gap-1.5">
          <div className="flex flex-col gap-1 pt-5">
            {timeBlocks.map((b) => (
              <span key={b.label} className="text-[10px] text-muted-foreground h-5 flex items-center">
                {b.label}
              </span>
            ))}
          </div>
          <div className="flex-1 grid grid-cols-7 gap-1">
            {dayLabels.map((d, i) => (
              <span key={i} className="text-[10px] text-muted-foreground text-center">
                {d}
              </span>
            ))}
            {timeBlocks.map((_, blockIdx) =>
              dayLabels.map((_, dayIdx) => {
                const count = heatmap[dayIdx][blockIdx];
                const intensity = count / maxCount;
                const bg =
                  intensity === 0
                    ? "bg-muted"
                    : intensity < 0.33
                      ? "bg-brand/20"
                      : intensity < 0.66
                        ? "bg-brand/45"
                        : "bg-brand/75";
                return (
                  <div
                    key={`${dayIdx}-${blockIdx}`}
                    className={`h-5 rounded-md ${bg} transition-colors`}
                    title={`${dayLabels[dayIdx]} ${timeBlocks[blockIdx].label}: ${count} sessions`}
                  />
                );
              }),
            )}
          </div>
        </div>

        {/* Optimal windows */}
        {windows.length > 0 && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-muted-foreground">{t("home.studyRhythm.bestTimes")}</span>
            {windows.map((w, i) => (
              <span
                key={i}
                className="text-xs px-2 py-0.5 rounded-full bg-brand-muted text-brand font-medium"
              >
                {formatStudyWindow(w)}
              </span>
            ))}
          </div>
        )}
      </div>
    </DashSection>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const t = useT();
  const tf = useTF();
  const { locale } = useLocale();
  const { courses, loading, error } = useCourseStore();
  const totalActiveGoals = courses.reduce((sum, c) => sum + (c.active_goal_count ?? 0), 0);
  const totalPendingApprovals = courses.reduce((sum, c) => sum + (c.pending_approval_count ?? 0), 0);
  const totalRunningTasks = courses.reduce((sum, c) => sum + (c.pending_task_count ?? 0), 0);

  const [health, setHealth] = useState<HealthStatus | null>(
    () => ttlCache.get<HealthStatus>("dash:health") ?? null,
  );
  const [reviewSummaries, setReviewSummaries] = useState<ReviewSummary[]>([]);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [pendingTasks, setPendingTasks] = useState<PendingTaskSummary[]>([]);
  const [actingTasks, setActingTasks] = useState<Set<string>>(new Set());
  const [modeRecommendations, setModeRecommendations] = useState<ModeRecommendation[]>([]);
  const [actingModeCourses, setActingModeCourses] = useState<Set<string>>(new Set());
  const [upcomingDeadlines, setUpcomingDeadlines] = useState<Array<StudyGoal & { courseName: string }>>([]);
  const [dailyDigest, setDailyDigest] = useState<AppNotification | null>(null);
  const [knowledgeDensity, setKnowledgeDensity] = useState<KnowledgeDensitySummary | null>(null);

  // Onboarding + single-course redirect
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onboarded = window.localStorage.getItem("opentutor_onboarded");
    if (!onboarded) {
      router.replace("/setup");
      return;
    }
    const state = useCourseStore.getState();
    if (!state.loading && state.courses.length === 1) {
      router.replace(`/course/${state.courses[0].id}`);
    }
  }, [router, courses, loading]);

  // Load courses and health + init study notifications
  useEffect(() => {
    useCourseStore.getState().fetchCourses();
    const refreshHealth = () =>
      getHealthStatus()
        .then((d) => { ttlCache.set("dash:health", d, 30_000); setHealth(d); })
        .catch((e) => console.error("[Dashboard] health check failed:", e));
    refreshHealth();
    const id = setInterval(refreshHealth, 30_000);
    const cleanupNotif = initStudyNotifications();
    return () => { clearInterval(id); cleanupNotif(); };
  }, []);

  // Fetch cross-course review summaries
  useEffect(() => {
    if (courses.length === 0) return;
    const fetchReviews = async () => {
      const results = await Promise.allSettled(
        courses.map(async (course) => {
          const session = await getReviewSession(course.id, 50);
          const items = session?.items ?? [];
          const overdue = items.filter((i) => i.urgency === "overdue").length;
          const urgent = items.filter((i) => i.urgency === "urgent").length;
          if (overdue > 0 || urgent > 0) {
            return {
              courseId: course.id,
              courseName: course.name,
              overdueCount: overdue,
              urgentCount: urgent,
              totalCount: items.length,
            } as ReviewSummary;
          }
          return null;
        }),
      );
      const summaries = results
        .filter((r): r is PromiseFulfilledResult<ReviewSummary | null> => r.status === "fulfilled")
        .map((r) => r.value)
        .filter((s): s is ReviewSummary => s !== null);
      summaries.sort((a, b) => b.overdueCount - a.overdueCount);
      setReviewSummaries(summaries);
    };
    fetchReviews();
  }, [courses]);

  // Fetch notifications (agent insights) + daily digest
  useEffect(() => {
    listNotifications({ unreadOnly: false, limit: 20 })
      .then((res) => {
        const all = res?.notifications ?? [];
        setNotifications(all.filter((n) => !n.read).slice(0, 5));
        // Find latest daily digest
        const digest = all.find((n) => n.category === "daily_brief");
        if (digest) setDailyDigest(digest);
      })
      .catch((e) => console.error("[Dashboard] notifications fetch failed:", e));
  }, []);

  // Fetch pending approval tasks for quick actions on Home.
  useEffect(() => {
    if (courses.length === 0) return;
    let cancelled = false;
    const fetchPendingTasks = async () => {
      const pending: PendingTaskSummary[] = [];
      await Promise.all(
        courses.map(async (course) => {
          try {
            const tasks = await listAgentTasks(course.id);
            tasks
              .filter((task) => task.status === "pending_approval")
              .forEach((task) => pending.push({ ...task, courseName: course.name }));
          } catch {
            // ignore per-course task failures
          }
        }),
      );
      pending.sort((a, b) => new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime());
      if (!cancelled) {
        setPendingTasks(pending.slice(0, 8));
      }
    };
    void fetchPendingTasks();
    return () => {
      cancelled = true;
    };
  }, [courses]);

  // Fetch upcoming deadlines from study goals
  useEffect(() => {
    if (courses.length === 0) return;
    const fetchDeadlines = async () => {
      const deadlines: Array<StudyGoal & { courseName: string }> = [];
      for (const course of courses) {
        try {
          const goals = await listStudyGoals(course.id, "active");
          for (const goal of goals) {
            if (goal.target_date) {
              const targetDate = new Date(goal.target_date);
              const now = new Date();
              const daysUntil = Math.ceil((targetDate.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
              if (daysUntil >= -1 && daysUntil <= 30) {
                deadlines.push({ ...goal, courseName: course.name });
              }
            }
          }
        } catch { /* ignore */ }
      }
      deadlines.sort((a, b) => new Date(a.target_date!).getTime() - new Date(b.target_date!).getTime());
      setUpcomingDeadlines(deadlines.slice(0, 10));
    };
    fetchDeadlines();
  }, [courses]);

  // Cross-course knowledge density (concept overlap across spaces)
  useEffect(() => {
    if (courses.length < 2) return;

    let cancelled = false;
    const fetchDensity = async () => {
      const conceptFreq = new Map<string, { count: number; display: string }>();

      for (const course of courses) {
        try {
          const graph = await getKnowledgeGraph(course.id);
          const seenInCourse = new Set<string>();
          for (const node of graph.nodes ?? []) {
            const normalized = normalizeConceptLabel(node.label ?? "");
            if (!normalized || seenInCourse.has(normalized)) continue;
            seenInCourse.add(normalized);
            const prev = conceptFreq.get(normalized);
            conceptFreq.set(normalized, {
              count: (prev?.count ?? 0) + 1,
              display: prev?.display ?? node.label,
            });
          }
        } catch {
          // Ignore per-course graph failures; compute from available graphs.
        }
      }

      const allConcepts = [...conceptFreq.values()];
      const shared = allConcepts.filter((v) => v.count >= 2);
      const topShared = [...shared]
        .sort((a, b) => b.count - a.count)
        .slice(0, 6)
        .map((v) => v.display);
      const totalConcepts = allConcepts.length;
      const sharedConcepts = shared.length;
      const densityPct = totalConcepts > 0
        ? Math.round((sharedConcepts / totalConcepts) * 100)
        : 0;

      if (!cancelled) {
        setKnowledgeDensity({
          totalConcepts,
          sharedConcepts,
          densityPct,
          topSharedConcepts: topShared,
        });
      }
    };

    void fetchDensity();
    return () => { cancelled = true; };
  }, [courses]);

  // Cross-course mode recommendations for Command Center.
  useEffect(() => {
    if (courses.length === 0) return;
    let cancelled = false;

    const fetchModeRecommendations = async () => {
      const next: ModeRecommendation[] = [];

      await Promise.all(
        courses.map(async (course) => {
          const currentMode = getCourseMode(course);
          if (!currentMode) return;

          const goals = await listStudyGoals(course.id, "active").catch(() => [] as StudyGoal[]);
          const now = Date.now();
          const deadlines = goals
            .filter((g) => g.target_date)
            .map((g) => ({
              goal: g,
              daysLeft: Math.ceil((new Date(g.target_date!).getTime() - now) / (1000 * 60 * 60 * 24)),
            }));
          const upcoming = deadlines
            .filter((d) => d.daysLeft >= 0 && d.daysLeft <= 7)
            .sort((a, b) => a.daysLeft - b.daysLeft)[0];
          const allDeadlinesPassed = deadlines.length > 0 && deadlines.every((d) => d.daysLeft < 0);

          let mastery: number | null = null;
          let errorRatePct: number | null = null;
          if (currentMode === "course_following" || currentMode === "self_paced") {
            const progress = await getCourseProgress(course.id).catch(() => null);
            if (progress) {
              mastery = Math.round((progress.average_mastery ?? 0) * 100);
              const totalAttempts = progress.mastered + progress.reviewed + progress.in_progress;
              if (totalAttempts > 10) {
                errorRatePct = Math.round((progress.in_progress / totalAttempts) * 100);
              }
            }
          }

          if (currentMode === "exam_prep" && allDeadlinesPassed) {
            if (isModeRecommendationSnoozed(course.id, "exam_passed")) return;
            next.push({
              courseId: course.id,
              courseName: course.name,
              currentMode,
              suggestedMode: "maintenance",
              recommendationKey: "exam_passed",
              reason: t("course.modeSuggestion.examPassed"),
              signals: [t("course.modeSuggestion.signal.deadlinesPassed")],
            });
            return;
          }

          if (currentMode === "course_following" || currentMode === "self_paced") {
            if (upcoming && errorRatePct != null && errorRatePct > 40) {
              if (isModeRecommendationSnoozed(course.id, "error_rate")) return;
              next.push({
                courseId: course.id,
                courseName: course.name,
                currentMode,
                suggestedMode: "exam_prep",
                recommendationKey: "error_rate",
                reason: tf("course.modeSuggestion.errorRateDetailed", { rate: errorRatePct, days: upcoming.daysLeft }),
                signals: [
                  tf("course.modeSuggestion.signal.errorRate", { rate: errorRatePct }),
                  tf("course.modeSuggestion.signal.deadline", { days: upcoming.daysLeft }),
                ],
              });
              return;
            }

            if (upcoming) {
              if (isModeRecommendationSnoozed(course.id, "deadline")) return;
              next.push({
                courseId: course.id,
                courseName: course.name,
                currentMode,
                suggestedMode: "exam_prep",
                recommendationKey: "deadline",
                reason: tf("course.modeSuggestion.deadline", { title: upcoming.goal.title, days: upcoming.daysLeft }),
                signals: [tf("course.modeSuggestion.signal.deadline", { days: upcoming.daysLeft })],
              });
              return;
            }

            if (mastery != null && mastery >= 85) {
              if (isModeRecommendationSnoozed(course.id, "mastery")) return;
              next.push({
                courseId: course.id,
                courseName: course.name,
                currentMode,
                suggestedMode: "maintenance",
                recommendationKey: "mastery",
                reason: tf("course.modeSuggestion.mastery", { mastery }),
                signals: [tf("course.modeSuggestion.signal.mastery", { mastery })],
              });
            }
          }
        }),
      );

      if (!cancelled) {
        setModeRecommendations(next.slice(0, 6));
      }
    };

    void fetchModeRecommendations();
    return () => {
      cancelled = true;
    };
  }, [courses, t, tf]);

  const totalUrgentReviews = reviewSummaries.reduce((s, r) => s + r.overdueCount + r.urgentCount, 0);
  const actOnTask = async (taskId: string, action: "approve" | "reject") => {
    setActingTasks((prev) => new Set(prev).add(taskId));
    try {
      if (action === "approve") {
        await approveAgentTask(taskId);
      } else {
        await rejectAgentTask(taskId);
      }
      await markTaskNotificationsRead(taskId).catch(() => undefined);
      setPendingTasks((prev) => prev.filter((task) => task.id !== taskId));
      setNotifications((prev) => prev.filter((notification) => !notificationMatchesTask(notification, taskId)));
    } catch {
      // keep current state; user can retry
    } finally {
      setActingTasks((prev) => {
        const next = new Set(prev);
        next.delete(taskId);
        return next;
      });
    }
  };
  const applyModeRecommendation = async (item: ModeRecommendation) => {
    setActingModeCourses((prev) => new Set(prev).add(item.courseId));
    try {
      const layout = buildLayoutFromMode(item.suggestedMode);
      localStorage.setItem(`opentutor_blocks_${item.courseId}`, JSON.stringify(layout));
      updateUnlockContext(item.courseId, { mode: item.suggestedMode });
      await updateCourseLayout(item.courseId, layout as unknown as Record<string, unknown>);
      await logAgentDecision({
        course_id: item.courseId,
        action: "apply_mode_recommendation",
        title: `${t("home.modeRecommendations.apply")} · ${item.courseName}`,
        reason: item.reason,
        decision_type: "mode_suggestion",
        source: "home_command_center",
        top_signal_type: "manual_override",
        metadata_json: {
          recommendation_key: item.recommendationKey,
          current_mode: item.currentMode,
          suggested_mode: item.suggestedMode,
          signals: item.signals,
        },
      }).catch(() => undefined);
      setModeRecommendations((prev) => prev.filter((rec) => rec.courseId !== item.courseId));
    } catch {
      // ignore; user can retry
    } finally {
      setActingModeCourses((prev) => {
        const next = new Set(prev);
        next.delete(item.courseId);
        return next;
      });
    }
  };
  const dismissModeRecommendation = (item: ModeRecommendation) => {
    snoozeModeRecommendation(item.courseId, item.recommendationKey);
    void logAgentDecision({
      course_id: item.courseId,
      action: "snooze_mode_recommendation",
      title: `${t("home.modeRecommendations.snooze")} · ${item.courseName}`,
      reason: item.reason,
      decision_type: "mode_suggestion",
      source: "home_command_center",
      top_signal_type: "manual_override",
      metadata_json: {
        recommendation_key: item.recommendationKey,
        current_mode: item.currentMode,
        suggested_mode: item.suggestedMode,
        signals: item.signals,
      },
    }).catch(() => undefined);
    setModeRecommendations((prev) =>
      prev.filter(
        (rec) =>
          !(rec.courseId === item.courseId && rec.recommendationKey === item.recommendationKey),
      ),
    );
  };
  const getDeadlineLabel = (daysUntil: number): string => {
    if (daysUntil <= 0) return t("home.deadline.overdue");
    if (daysUntil === 1) return t("home.deadline.tomorrow");
    return tf("home.deadline.inDays", { days: daysUntil });
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="flex min-h-screen flex-col md:flex-row">
        {/* Left Navigation */}
        <aside className="w-full shrink-0 border-b border-border/60 bg-card p-4 md:w-[220px] md:border-b-0 md:border-r md:flex md:flex-col md:gap-6 md:p-5">
          <div className="flex items-center gap-2.5 px-1 py-1">
            <div className="size-8 rounded-xl bg-brand flex items-center justify-center">
              <BookOpen className="size-4 text-brand-foreground" />
            </div>
            <span className="text-base font-bold text-foreground tracking-tight">OpenTutor</span>
          </div>
          <nav className="mt-3 flex flex-wrap gap-1 md:mt-2 md:flex-col">
            <span className="px-3 py-2.5 rounded-xl text-sm font-medium bg-brand-muted text-brand flex items-center gap-2">
              <Sparkles className="size-3.5" />
              {t("nav.dashboard")}
            </span>
            <button
              type="button"
              onClick={() => router.push("/settings")}
              className="px-3 py-2.5 rounded-xl text-sm text-muted-foreground hover:bg-muted/60 hover:text-foreground transition-colors text-left flex items-center gap-2"
            >
              <Settings className="size-3.5" />
              {t("nav.settings")}
            </button>
          </nav>
          {health?.deployment_mode === "single_user" && (
            <span className="mt-3 inline-flex w-fit rounded-full bg-muted px-3 py-1.5 text-center text-[11px] font-medium text-muted-foreground md:mt-auto">
              {t("dashboard.singleUser")}
            </span>
          )}
        </aside>

        {/* Main Content — Command Center */}
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
                <h1 className="text-2xl font-bold tracking-tight text-foreground">
                  {t("dashboard.title")}
                </h1>
                <p className="text-sm text-muted-foreground">
                  {t("dashboard.subtitle")}
                </p>
              </div>
              <button
                type="button"
                onClick={() => router.push("/new")}
                className="h-10 px-6 bg-brand text-brand-foreground rounded-full text-sm font-medium hover:opacity-90 transition-all hover:shadow-md shrink-0 self-start sm:self-auto"
              >
                + {t("dashboard.create")}
              </button>
            </div>

            {/* Overview stats */}
            {courses.length > 0 && (
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
            )}

            {/* Today's Digest */}
            {courses.length > 0 && (
              <DashSection title={t("home.todayDigest")} icon={Sun}>
                {dailyDigest ? (
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-foreground">{dailyDigest.title}</p>
                    <p className="text-sm text-muted-foreground whitespace-pre-line">{dailyDigest.body}</p>
                  </div>
                ) : (
                  <DigestFallback
                    courses={courses}
                    reviewSummaries={reviewSummaries}
                    upcomingDeadlines={upcomingDeadlines}
                    t={t}
                    tf={tf}
                  />
                )}
              </DashSection>
            )}

            {/* Upcoming Deadlines */}
            {courses.length > 0 && (
              <DashSection
                title={t("home.upcomingDeadlines")}
                icon={CalendarDays}
                badge={upcomingDeadlines.length}
              >
                {upcomingDeadlines.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t("home.upcomingDeadlines.empty")}</p>
                ) : (
                  <div className="space-y-2">
                    {upcomingDeadlines.map((d) => {
                      const daysUntil = Math.ceil(
                        (new Date(d.target_date!).getTime() - getDashboardNowMs()) / (1000 * 60 * 60 * 24),
                      );
                      const urgencyClass =
                        daysUntil <= 0
                          ? "text-destructive font-semibold"
                          : daysUntil <= 3
                            ? "text-warning font-medium"
                            : "text-muted-foreground";
                      const label = getDeadlineLabel(daysUntil);
                      return (
                        <button
                          key={d.id}
                          type="button"
                          onClick={() => d.course_id && router.push(`/course/${d.course_id}/plan`)}
                          className="w-full flex items-center gap-3 rounded-xl bg-muted/30 p-3.5 text-left hover:bg-muted/50 transition-colors"
                        >
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-foreground truncate">{d.title}</p>
                            <p className="text-xs text-muted-foreground truncate">{d.courseName}</p>
                          </div>
                          <span className={`text-xs shrink-0 ${urgencyClass}`}>{label}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </DashSection>
            )}

            {/* Urgent Reviews — cross-course LECTOR aggregation */}
            {courses.length > 0 && (
              <DashSection
                title={t("home.urgentReviews")}
                icon={RotateCcw}
                badge={totalUrgentReviews}
              >
                {reviewSummaries.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t("home.urgentReviews.empty")}</p>
                ) : (
                  <div className="space-y-2">
                    {reviewSummaries.map((rs) => (
                      <button
                        key={rs.courseId}
                        type="button"
                        onClick={() => router.push(`/course/${rs.courseId}/review`)}
                        className="w-full flex items-center gap-3 rounded-xl bg-muted/30 p-3.5 text-left hover:bg-muted/50 transition-colors"
                      >
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-foreground truncate">{rs.courseName}</p>
                          <p className="text-xs text-muted-foreground">
                            {rs.overdueCount > 0 && (
                              <span className="text-destructive font-medium">{tf("home.reviews.overdue", { count: rs.overdueCount })}</span>
                            )}
                            {rs.overdueCount > 0 && rs.urgentCount > 0 && " · "}
                            {rs.urgentCount > 0 && (
                              <span className="text-warning font-medium">{tf("home.reviews.urgent", { count: rs.urgentCount })}</span>
                            )}
                            {" · "}{tf("home.reviews.total", { count: rs.totalCount })}
                          </p>
                        </div>
                        <ArrowRight className="size-4 text-muted-foreground shrink-0" />
                      </button>
                    ))}
                  </div>
                )}
              </DashSection>
            )}

            {/* Cross-course Knowledge Density */}
            {courses.length > 1 && (
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
                      <div
                        className="h-full bg-brand rounded-full transition-all duration-500"
                        style={{ width: `${knowledgeDensity.densityPct}%` }}
                      />
                    </div>

                    {knowledgeDensity.topSharedConcepts.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {knowledgeDensity.topSharedConcepts.map((name) => (
                          <span
                            key={name}
                            className="text-[11px] px-2 py-0.5 rounded-full bg-brand-muted text-brand"
                          >
                            {name}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </DashSection>
            )}

            {/* Agent Insights — cross-course notifications */}
            {courses.length > 0 && (
              <DashSection
                title={t("home.agentInsights")}
                icon={Sparkles}
                badge={notifications.length}
              >
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
                        <div
                          key={n.id}
                          className="flex items-start gap-3 rounded-xl bg-muted/30 p-3.5"
                        >
                          <Sparkles className="size-4 text-brand shrink-0 mt-0.5" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-foreground">{n.title}</p>
                            <p className="text-xs text-muted-foreground mt-0.5">{n.body}</p>
                            {ctaPath ? (
                              <button
                                type="button"
                                onClick={() => router.push(ctaPath)}
                                className="mt-1.5 text-[11px] font-medium text-brand hover:underline"
                              >
                                {ctaLabel}
                              </button>
                            ) : null}
                          </div>
                          <span className="text-[10px] text-muted-foreground shrink-0">
                            {formatDate(n.created_at)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </DashSection>
            )}

            {/* Pending Approvals — quick Tier-2 decisions */}
            {courses.length > 0 && (
              <DashSection
                title={t("home.pendingApprovals.title")}
                icon={Sparkles}
                badge={pendingTasks.length}
              >
                {pendingTasks.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t("home.pendingApprovals.empty")}</p>
                ) : (
                  <div className="space-y-2">
                    {pendingTasks.map((task) => (
                      <div key={task.id} className="rounded-xl bg-muted/30 p-3.5">
                        <div className="flex items-start gap-3">
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium text-foreground">{task.title}</p>
                            {task.summary ? (
                              <p className="text-xs text-muted-foreground mt-0.5">{task.summary}</p>
                            ) : null}
                            <p className="text-[11px] text-muted-foreground mt-1">
                              {task.courseName || t("home.pendingApprovals.courseUnknown")} ·{" "}
                              {tf("home.pendingApprovals.source", { taskType: task.task_type, source: task.source })}
                            </p>
                            {task.approval_reason ? (
                              <p className="text-[11px] text-muted-foreground mt-1">
                                {t("home.pendingApprovals.reason")} {task.approval_reason}
                              </p>
                            ) : null}
                          </div>
                          <div className="flex shrink-0 gap-1.5">
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={actingTasks.has(task.id)}
                              onClick={() => void actOnTask(task.id, "reject")}
                            >
                              {t("home.pendingApprovals.reject")}
                            </Button>
                            <Button
                              size="sm"
                              disabled={actingTasks.has(task.id)}
                              onClick={() => void actOnTask(task.id, "approve")}
                            >
                              {t("home.pendingApprovals.approve")}
                            </Button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </DashSection>
            )}

            {/* Mode Recommendations — cross-course mode transitions */}
            {courses.length > 0 && (
              <DashSection
                title={t("home.modeRecommendations.title")}
                icon={Sparkles}
                badge={modeRecommendations.length}
              >
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
                            {item.signals.length > 0 ? (
                              <div className="mt-1.5 flex flex-wrap gap-1">
                                {item.signals.map((signal) => (
                                  <span
                                    key={`${item.courseId}-${signal}`}
                                    className="inline-flex rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground"
                                  >
                                    {signal}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                          </div>
                          <div className="flex shrink-0 gap-1.5">
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={actingModeCourses.has(item.courseId)}
                              onClick={() => dismissModeRecommendation(item)}
                            >
                              {t("home.modeRecommendations.snooze")}
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => router.push(`/course/${item.courseId}`)}
                            >
                              {t("home.modeRecommendations.openCourse")}
                            </Button>
                            <Button
                              size="sm"
                              disabled={actingModeCourses.has(item.courseId)}
                              onClick={() => void applyModeRecommendation(item)}
                            >
                              {t("home.modeRecommendations.apply")}
                            </Button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </DashSection>
            )}

            {/* Learning Rhythm */}
            {courses.length > 0 && <LearningRhythm t={t} />}

            {/* Your Spaces */}
            {loading && <CourseCardsSkeleton />}

            {courses.length > 0 && (
              <DashSection title={t("home.yourSpaces")} icon={BookOpen}>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {courses.map((course, idx) => {
                    const color = CARD_COLORS[idx % CARD_COLORS.length];
                    const initials = getInitials(course.name);
                    const hasPending = (course.pending_approval_count ?? 0) > 0;
                    return (
                      <button
                        type="button"
                        key={course.id}
                        onClick={() => router.push(`/course/${course.id}`)}
                        className="p-5 rounded-2xl flex flex-col gap-3 text-left card-lift bg-card group"
                      >
                        <div className="flex items-center gap-3 w-full">
                          <div className={`w-10 h-10 ${color.bg} rounded-xl flex items-center justify-center shrink-0`}>
                            <span className={`font-bold text-xs ${color.text}`}>{initials}</span>
                          </div>
                          <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                            <span className="font-semibold text-sm text-foreground truncate group-hover:text-brand transition-colors">{course.name}</span>
                            <span className="text-[11px] text-muted-foreground">
                              {formatDate(course.updated_at ?? course.created_at)}
                            </span>
                          </div>
                          <ArrowRight className="size-4 text-muted-foreground/0 group-hover:text-muted-foreground transition-all shrink-0" />
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs text-muted-foreground line-clamp-1 flex-1">
                            {course.description || `${t("dashboard.scenePrefix")}: ${course.last_scene_id || "study_session"}`}
                          </span>
                          <ModeBadge mode={getCourseMode(course)} />
                        </div>
                        {hasPending && (
                          <span className="inline-flex w-fit rounded-full px-2.5 py-0.5 text-[11px] font-medium bg-warning-muted text-warning">
                            {locale === "zh"
                              ? `${course.pending_approval_count}${t("dashboard.pendingApprovalsBadge")}`
                              : `${course.pending_approval_count} ${t("dashboard.pendingApprovalsBadge")}`}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </DashSection>
            )}

            {/* Empty State */}
            {!loading && courses.length === 0 && (
              <div className="text-center py-24 flex flex-col items-center gap-5 animate-fade-in">
                <div className="size-16 rounded-2xl bg-brand-muted flex items-center justify-center">
                  <BookOpen className="size-7 text-brand" />
                </div>
                <h2 className="text-lg font-bold text-foreground">{t("dashboard.empty")}</h2>
                <p className="text-sm text-muted-foreground max-w-sm leading-relaxed">
                  {t("dashboard.emptyDescription")}
                </p>
                <button
                  type="button"
                  onClick={() => router.push("/setup?step=content")}
                  className="h-11 px-7 bg-brand text-brand-foreground rounded-full text-sm font-medium hover:opacity-90 transition-all hover:shadow-md"
                >
                  {t("dashboard.create")}
                </button>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
