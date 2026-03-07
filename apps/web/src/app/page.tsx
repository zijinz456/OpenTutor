"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useCourseStore } from "@/store/course";
import {
  getHealthStatus,
  getKnowledgeGraph,
  getReviewSession,
  listNotifications,
  type HealthStatus,
  type Course,
  type AppNotification,
} from "@/lib/api";
import { listStudyGoals, type StudyGoal } from "@/lib/api/progress";
import { ttlCache } from "@/lib/cache";
import { useLocale, useT } from "@/lib/i18n-context";
import { RuntimeAlert } from "@/components/shared/runtime-alert";
import { ModeBadge } from "@/components/course/mode-selector";
import type { LearningMode, SpaceLayout } from "@/lib/block-system/types";
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
const DASHBOARD_NOW_MS = Date.now();

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

interface KnowledgeDensitySummary {
  totalConcepts: number;
  sharedConcepts: number;
  densityPct: number;
  topSharedConcepts: string[];
}

function normalizeConceptLabel(label: string): string {
  return label.trim().toLowerCase().replace(/\s+/g, " ");
}

function CourseCardsSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="p-5 border border-border rounded-xl flex flex-col gap-3 animate-pulse">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-muted rounded-lg" />
            <div className="flex flex-col gap-1.5 flex-1">
              <div className="h-4 bg-muted rounded w-3/4" />
              <div className="h-3 bg-muted rounded w-1/2" />
            </div>
          </div>
          <div className="h-3 bg-muted rounded w-2/3" />
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
    <section className="rounded-xl border border-border bg-card overflow-hidden">
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-muted/40 transition-colors"
      >
        <Icon className="size-4 text-muted-foreground shrink-0" />
        <span className="text-sm font-semibold text-foreground flex-1">{title}</span>
        {badge != null && badge > 0 && (
          <span className="text-[11px] font-medium bg-destructive/10 text-destructive px-2 py-0.5 rounded-full">
            {badge}
          </span>
        )}
        <span className={`text-muted-foreground transition-transform ${collapsed ? "" : "rotate-180"}`}>
          <svg className="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path d="M19 9l-7 7-7-7" />
          </svg>
        </span>
      </button>
      {!collapsed && <div className="px-4 pb-4">{children}</div>}
    </section>
  );
}

/** Client-side digest fallback when backend daily_brief is not available. */
function DigestFallback({
  courses,
  reviewSummaries,
  upcomingDeadlines,
  t,
}: {
  courses: Course[];
  reviewSummaries: ReviewSummary[];
  upcomingDeadlines: Array<{ title: string; target_date: string | null }>;
  t: (key: string) => string;
}) {
  const persona = getPersona();
  if (persona.totalSessions === 0) {
    return <p className="text-sm text-muted-foreground">{t("home.todayDigest.empty")}</p>;
  }

  const totalReviewItems = reviewSummaries.reduce((s, r) => s + r.overdueCount + r.urgentCount, 0);
  const nextDeadline = upcomingDeadlines[0];
  const daysUntilDeadline = nextDeadline?.target_date
    ? Math.ceil((new Date(nextDeadline.target_date).getTime() - DASHBOARD_NOW_MS) / (1000 * 60 * 60 * 24))
    : null;

  return (
    <div className="space-y-1.5 text-sm text-muted-foreground">
      <p>
        <span className="text-foreground font-medium">{courses.length}</span>{" "}
        {courses.length === 1 ? "active space" : "active spaces"} ·{" "}
        <span className="text-foreground font-medium">{persona.totalSessions}</span> sessions tracked
      </p>
      {totalReviewItems > 0 && (
        <p>
          <span className="text-warning font-medium">{totalReviewItems}</span>{" "}
          {t("home.urgentReviews.conceptsFading")}
        </p>
      )}
      {daysUntilDeadline != null && daysUntilDeadline >= 0 && (
        <p>
          Next deadline: <span className="text-foreground font-medium">{nextDeadline!.title}</span>{" "}
          in {daysUntilDeadline}d
        </p>
      )}
    </div>
  );
}

/** Learning rhythm visualization from Learner's Persona data. */
function LearningRhythm() {
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
    <DashSection title="Study Rhythm" icon={Clock}>
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
                    className={`h-5 rounded-sm ${bg} transition-colors`}
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
            <span className="text-xs text-muted-foreground">Best times:</span>
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
      const summaries: ReviewSummary[] = [];
      for (const course of courses) {
        try {
          const session = await getReviewSession(course.id, 50);
          const items = session?.items ?? [];
          const overdue = items.filter((i) => i.urgency === "overdue").length;
          const urgent = items.filter((i) => i.urgency === "urgent").length;
          if (overdue > 0 || urgent > 0) {
            summaries.push({
              courseId: course.id,
              courseName: course.name,
              overdueCount: overdue,
              urgentCount: urgent,
              totalCount: items.length,
            });
          }
        } catch { /* ignore */ }
      }
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

  const totalUrgentReviews = reviewSummaries.reduce((s, r) => s + r.overdueCount + r.urgentCount, 0);

  return (
    <div className="min-h-screen bg-background">
      <div className="flex min-h-screen flex-col md:flex-row">
        {/* Left Navigation */}
        <aside className="w-full shrink-0 border-b border-border bg-sidebar p-4 md:w-[200px] md:border-b-0 md:border-r md:flex md:flex-col md:gap-6">
          <div className="flex items-center gap-2 px-2 py-1">
            <span className="text-base font-bold text-sidebar-foreground tracking-tight">OpenTutor</span>
          </div>
          <nav className="mt-3 flex flex-wrap gap-1 md:mt-0 md:flex-col">
            <span className="px-3 py-2 rounded-md text-sm font-semibold bg-sidebar-accent text-sidebar-accent-foreground">
              {t("nav.dashboard")}
            </span>
            <button
              type="button"
              onClick={() => router.push("/settings")}
              className="px-3 py-2 rounded-md text-sm text-sidebar-foreground hover:bg-sidebar-accent transition-colors text-left"
            >
              <Settings className="size-3.5 inline mr-1.5" />
              {t("nav.settings")}
            </button>
          </nav>
          {health?.deployment_mode === "single_user" && (
            <span className="mt-3 inline-flex w-fit rounded-md bg-muted px-3 py-1.5 text-center text-[11px] font-medium text-muted-foreground md:mt-auto">
              {t("dashboard.singleUser")}
            </span>
          )}
        </aside>

        {/* Main Content — Command Center */}
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-4xl flex-col gap-5 px-4 py-6 sm:px-6 md:px-10 md:py-10">
            <RuntimeAlert health={health} />

            {error && (
              <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                {t("dashboard.loadErrorPrefix")}: {error}
              </div>
            )}

            {/* Title + New Space */}
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div className="flex flex-col gap-1">
                <h1 className="text-2xl font-semibold tracking-tight text-foreground">
                  {t("dashboard.title")}
                </h1>
                <p className="text-sm text-muted-foreground">
                  {t("dashboard.subtitle")}
                </p>
              </div>
              <button
                type="button"
                onClick={() => router.push("/new")}
                className="h-9 px-5 bg-brand text-brand-foreground rounded-lg text-sm font-medium hover:opacity-90 transition-opacity shrink-0 self-start sm:self-auto"
              >
                + {t("dashboard.create")}
              </button>
            </div>

            {/* Overview stats */}
            {courses.length > 0 && (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div className="rounded-xl border border-border bg-card p-4">
                  <div className="text-xs text-muted-foreground mb-1">{t("dashboard.activeGoals")}</div>
                  <div className="text-xl font-semibold text-foreground">{totalActiveGoals}</div>
                </div>
                <div className="rounded-xl border border-border bg-card p-4">
                  <div className="text-xs text-muted-foreground mb-1">{t("dashboard.pendingApprovals")}</div>
                  <div className="text-xl font-semibold text-foreground">{totalPendingApprovals}</div>
                </div>
                <div className="rounded-xl border border-border bg-card p-4">
                  <div className="text-xs text-muted-foreground mb-1">{t("dashboard.runningTasks")}</div>
                  <div className="text-xl font-semibold text-foreground">{totalRunningTasks}</div>
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
                  />
                )}
              </DashSection>
            )}

            {/* Upcoming Deadlines */}
            {courses.length > 0 && upcomingDeadlines.length > 0 && (
              <DashSection
                title={t("home.upcomingDeadlines")}
                icon={CalendarDays}
                badge={upcomingDeadlines.length}
              >
                <div className="space-y-2">
                  {upcomingDeadlines.map((d) => {
                    const daysUntil = Math.ceil(
                      (new Date(d.target_date!).getTime() - DASHBOARD_NOW_MS) / (1000 * 60 * 60 * 24),
                    );
                    const urgencyClass =
                      daysUntil <= 0
                        ? "text-destructive font-semibold"
                        : daysUntil <= 3
                          ? "text-warning font-medium"
                          : "text-muted-foreground";
                    const label =
                      daysUntil <= 0
                        ? locale === "zh" ? "已逾期" : "Overdue"
                        : daysUntil === 1
                          ? locale === "zh" ? "明天" : "Tomorrow"
                          : locale === "zh"
                            ? `${daysUntil} 天后`
                            : `${daysUntil}d`;
                    return (
                      <button
                        key={d.id}
                        type="button"
                        onClick={() => d.course_id && router.push(`/course/${d.course_id}/plan`)}
                        className="w-full flex items-center gap-3 rounded-lg border border-border p-3 text-left hover:bg-muted/40 transition-colors"
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
                        className="w-full flex items-center gap-3 rounded-lg border border-border p-3 text-left hover:bg-muted/40 transition-colors"
                      >
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-foreground truncate">{rs.courseName}</p>
                          <p className="text-xs text-muted-foreground">
                            {rs.overdueCount > 0 && (
                              <span className="text-destructive font-medium">{rs.overdueCount} overdue</span>
                            )}
                            {rs.overdueCount > 0 && rs.urgentCount > 0 && " · "}
                            {rs.urgentCount > 0 && (
                              <span className="text-warning font-medium">{rs.urgentCount} urgent</span>
                            )}
                            {" · "}{rs.totalCount} total
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
                      <div className="rounded-lg border border-border p-3">
                        <p className="text-[11px] text-muted-foreground">{t("home.knowledgeDensity.shared")}</p>
                        <p className="text-base font-semibold text-foreground">{knowledgeDensity.sharedConcepts}</p>
                      </div>
                      <div className="rounded-lg border border-border p-3">
                        <p className="text-[11px] text-muted-foreground">{t("home.knowledgeDensity.total")}</p>
                        <p className="text-base font-semibold text-foreground">{knowledgeDensity.totalConcepts}</p>
                      </div>
                      <div className="rounded-lg border border-border p-3">
                        <p className="text-[11px] text-muted-foreground">{t("home.knowledgeDensity.overlap")}</p>
                        <p className="text-base font-semibold text-brand">{knowledgeDensity.densityPct}%</p>
                      </div>
                    </div>

                    <div className="h-2 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full bg-brand transition-all"
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
            {courses.length > 0 && notifications.length > 0 && (
              <DashSection
                title={t("home.agentInsights")}
                icon={Sparkles}
                badge={notifications.length}
              >
                <div className="space-y-2">
                  {notifications.map((n) => (
                    <div
                      key={n.id}
                      className="flex items-start gap-3 rounded-lg border border-border p-3"
                    >
                      <Sparkles className="size-4 text-brand shrink-0 mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-foreground">{n.title}</p>
                        <p className="text-xs text-muted-foreground mt-0.5">{n.body}</p>
                      </div>
                      <span className="text-[10px] text-muted-foreground shrink-0">
                        {formatDate(n.created_at)}
                      </span>
                    </div>
                  ))}
                </div>
              </DashSection>
            )}

            {/* Learning Rhythm */}
            {courses.length > 0 && <LearningRhythm />}

            {/* Your Spaces */}
            {loading && <CourseCardsSkeleton />}

            {courses.length > 0 && (
              <DashSection title={t("home.yourSpaces")} icon={BookOpen}>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {courses.map((course, idx) => {
                    const color = CARD_COLORS[idx % CARD_COLORS.length];
                    const initials = getInitials(course.name);
                    const hasPending = (course.pending_approval_count ?? 0) > 0;
                    return (
                      <button
                        type="button"
                        key={course.id}
                        onClick={() => router.push(`/course/${course.id}`)}
                        className="p-4 border border-border rounded-xl flex flex-col gap-2.5 text-left hover:border-brand hover:shadow-sm transition-all bg-card"
                      >
                        <div className="flex items-center gap-3 w-full">
                          <div className={`w-9 h-9 ${color.bg} rounded-lg flex items-center justify-center shrink-0`}>
                            <span className={`font-bold text-xs ${color.text}`}>{initials}</span>
                          </div>
                          <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                            <span className="font-semibold text-sm text-foreground truncate">{course.name}</span>
                            <span className="text-[11px] text-muted-foreground">
                              {formatDate(course.updated_at ?? course.created_at)}
                            </span>
                          </div>
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
              <div className="text-center py-20 flex flex-col items-center gap-4">
                <h2 className="text-lg font-semibold text-foreground">{t("dashboard.empty")}</h2>
                <p className="text-sm text-muted-foreground max-w-sm">
                  {t("dashboard.emptyDescription")}
                </p>
                <button
                  type="button"
                  onClick={() => router.push("/setup?step=content")}
                  className="h-10 px-6 bg-brand text-brand-foreground rounded-lg text-sm font-medium hover:opacity-90 transition-opacity"
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
