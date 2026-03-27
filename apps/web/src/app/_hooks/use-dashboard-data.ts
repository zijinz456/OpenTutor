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
  type AppNotification,
  listStudyGoals,
  type StudyGoal,
} from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import { useT, useTF } from "@/lib/i18n-context";
import { buildLayoutFromMode } from "@/lib/block-system/templates";
import { updateUnlockContext } from "@/lib/block-system/feature-unlock";
import { saveStoredSpaceLayout } from "@/lib/block-system/layout-storage";
import { initStudyNotifications } from "@/lib/study-notifications";
import {
  getCourseMode,
  isModeRecommendationSnoozed,
  snoozeModeRecommendation,
  notificationMatchesTask,
  normalizeConceptLabel,
  type ReviewSummary,
  type PendingTaskSummary,
  type KnowledgeDensitySummary,
  type ModeRecommendation,
} from "../_components/dashboard-utils";

export function useDashboardData() {
  const router = useRouter();
  const t = useT();
  const tf = useTF();
  const { courses, loading, error } = useCourseStore();

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

  const totalActiveGoals = courses.reduce((sum, c) => sum + (c.active_goal_count ?? 0), 0);
  const totalPendingApprovals = courses.reduce((sum, c) => sum + (c.pending_approval_count ?? 0), 0);
  const totalRunningTasks = courses.reduce((sum, c) => sum + (c.pending_task_count ?? 0), 0);
  const totalUrgentReviews = reviewSummaries.reduce((s, r) => s + r.overdueCount + r.urgentCount, 0);

  // Onboarding + single-course redirect (only after initial fetch completes)
  const [fetchTriggered, setFetchTriggered] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!fetchTriggered || loading) return; // wait for initial fetch to complete

    // If courses exist, mark onboarded and skip setup
    if (courses.length > 0) {
      try { window.localStorage.setItem("opentutor_onboarded", "true"); } catch { /* quota */ }
      if (courses.length === 1) {
        router.replace(`/course/${courses[0].id}`);
      }
      return;
    }

    // No courses after fetch — check onboarded flag
    const onboarded = window.localStorage.getItem("opentutor_onboarded");
    if (!onboarded) {
      router.replace("/setup");
    }
  }, [router, courses, loading, fetchTriggered]);

  // Load courses and health + init study notifications
  useEffect(() => {
    useCourseStore.getState().fetchCourses().then(() => setFetchTriggered(true));
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
    let cancelled = false;
    const fetchReviews = async () => {
      const results = await Promise.allSettled(
        courses.map(async (course) => {
          const session = await getReviewSession(course.id, 50);
          const items = session?.items ?? [];
          const overdue = items.filter((i) => i.urgency === "overdue").length;
          const urgent = items.filter((i) => i.urgency === "urgent").length;
          if (overdue > 0 || urgent > 0) {
            return { courseId: course.id, courseName: course.name, overdueCount: overdue, urgentCount: urgent, totalCount: items.length } as ReviewSummary;
          }
          return null;
        }),
      );
      if (cancelled) return;
      const summaries = results
        .filter((r): r is PromiseFulfilledResult<ReviewSummary | null> => r.status === "fulfilled")
        .map((r) => r.value)
        .filter((s): s is ReviewSummary => s !== null);
      summaries.sort((a, b) => b.overdueCount - a.overdueCount);
      setReviewSummaries(summaries);
    };
    fetchReviews();
    return () => { cancelled = true; };
  }, [courses]);

  // Fetch notifications (agent insights) + daily digest
  useEffect(() => {
    listNotifications({ unreadOnly: false, limit: 20 })
      .then((res) => {
        const all = res?.notifications ?? [];
        setNotifications(all.filter((n) => !n.read).slice(0, 5));
        const digest = all.find((n) => n.category === "daily_brief");
        if (digest) setDailyDigest(digest);
      })
      .catch((e) => console.error("[Dashboard] notifications fetch failed:", e));
  }, []);

  // Fetch pending approval tasks
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
          } catch (e) { console.warn("[Dashboard] tasks fetch failed for course %s:", course.id, e); }
        }),
      );
      pending.sort((a, b) => new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime());
      if (!cancelled) setPendingTasks(pending.slice(0, 8));
    };
    void fetchPendingTasks();
    return () => { cancelled = true; };
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
        } catch (e) { console.warn("[Dashboard] goals fetch failed for course %s:", course.id, e); }
      }
      deadlines.sort((a, b) => new Date(a.target_date!).getTime() - new Date(b.target_date!).getTime());
      setUpcomingDeadlines(deadlines.slice(0, 10));
    };
    fetchDeadlines();
  }, [courses]);

  // Cross-course knowledge density
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
            conceptFreq.set(normalized, { count: (prev?.count ?? 0) + 1, display: prev?.display ?? node.label });
          }
        } catch (e) { console.warn("[Dashboard] knowledge graph failed for course %s:", course.id, e); }
      }
      const allConcepts = [...conceptFreq.values()];
      const shared = allConcepts.filter((v) => v.count >= 2);
      const topShared = [...shared].sort((a, b) => b.count - a.count).slice(0, 6).map((v) => v.display);
      const totalConcepts = allConcepts.length;
      const sharedConcepts = shared.length;
      const densityPct = totalConcepts > 0 ? Math.round((sharedConcepts / totalConcepts) * 100) : 0;
      if (!cancelled) setKnowledgeDensity({ totalConcepts, sharedConcepts, densityPct, topSharedConcepts: topShared });
    };
    void fetchDensity();
    return () => { cancelled = true; };
  }, [courses]);

  // Cross-course mode recommendations
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
            .map((g) => ({ goal: g, daysLeft: Math.ceil((new Date(g.target_date!).getTime() - now) / (1000 * 60 * 60 * 24)) }));
          const upcoming = deadlines.filter((d) => d.daysLeft >= 0 && d.daysLeft <= 7).sort((a, b) => a.daysLeft - b.daysLeft)[0];
          const allDeadlinesPassed = deadlines.length > 0 && deadlines.every((d) => d.daysLeft < 0);

          let mastery: number | null = null;
          let errorRatePct: number | null = null;
          if (currentMode === "course_following" || currentMode === "self_paced") {
            const progress = await getCourseProgress(course.id).catch(() => null);
            if (progress) {
              mastery = Math.round((progress.average_mastery ?? 0) * 100);
              const totalAttempts = progress.mastered + progress.reviewed + progress.in_progress;
              if (totalAttempts > 10) errorRatePct = Math.round((progress.in_progress / totalAttempts) * 100);
            }
          }

          if (currentMode === "exam_prep" && allDeadlinesPassed) {
            if (isModeRecommendationSnoozed(course.id, "exam_passed")) return;
            next.push({ courseId: course.id, courseName: course.name, currentMode, suggestedMode: "maintenance", recommendationKey: "exam_passed", reason: t("course.modeSuggestion.examPassed"), signals: [t("course.modeSuggestion.signal.deadlinesPassed")] });
            return;
          }
          if (currentMode === "course_following" || currentMode === "self_paced") {
            if (upcoming && errorRatePct != null && errorRatePct > 40) {
              if (isModeRecommendationSnoozed(course.id, "error_rate")) return;
              next.push({ courseId: course.id, courseName: course.name, currentMode, suggestedMode: "exam_prep", recommendationKey: "error_rate", reason: tf("course.modeSuggestion.errorRateDetailed", { rate: errorRatePct, days: upcoming.daysLeft }), signals: [tf("course.modeSuggestion.signal.errorRate", { rate: errorRatePct }), tf("course.modeSuggestion.signal.deadline", { days: upcoming.daysLeft })] });
              return;
            }
            if (upcoming) {
              if (isModeRecommendationSnoozed(course.id, "deadline")) return;
              next.push({ courseId: course.id, courseName: course.name, currentMode, suggestedMode: "exam_prep", recommendationKey: "deadline", reason: tf("course.modeSuggestion.deadline", { title: upcoming.goal.title, days: upcoming.daysLeft }), signals: [tf("course.modeSuggestion.signal.deadline", { days: upcoming.daysLeft })] });
              return;
            }
            if (mastery != null && mastery >= 85) {
              if (isModeRecommendationSnoozed(course.id, "mastery")) return;
              next.push({ courseId: course.id, courseName: course.name, currentMode, suggestedMode: "maintenance", recommendationKey: "mastery", reason: tf("course.modeSuggestion.mastery", { mastery }), signals: [tf("course.modeSuggestion.signal.mastery", { mastery })] });
            }
          }
        }),
      );
      if (!cancelled) setModeRecommendations(next.slice(0, 6));
    };
    void fetchModeRecommendations();
    return () => { cancelled = true; };
  }, [courses, t, tf]);

  // Action handlers
  const actOnTask = async (taskId: string, action: "approve" | "reject") => {
    setActingTasks((prev) => new Set(prev).add(taskId));
    try {
      if (action === "approve") await approveAgentTask(taskId);
      else await rejectAgentTask(taskId);
      await markTaskNotificationsRead(taskId).catch(() => undefined);
      setPendingTasks((prev) => prev.filter((task) => task.id !== taskId));
      setNotifications((prev) => prev.filter((notification) => !notificationMatchesTask(notification, taskId)));
    } catch (e) { console.warn("[Dashboard] task action failed:", e); } finally {
      setActingTasks((prev) => { const next = new Set(prev); next.delete(taskId); return next; });
    }
  };

  const applyModeRecommendation = async (item: ModeRecommendation) => {
    setActingModeCourses((prev) => new Set(prev).add(item.courseId));
    try {
      const layout = buildLayoutFromMode(item.suggestedMode);
      saveStoredSpaceLayout(item.courseId, layout);
      updateUnlockContext(item.courseId, { mode: item.suggestedMode });
      await updateCourseLayout(item.courseId, layout);
      await logAgentDecision({
        course_id: item.courseId, action: "apply_mode_recommendation",
        title: `${t("home.modeRecommendations.apply")} · ${item.courseName}`, reason: item.reason,
        decision_type: "mode_suggestion", source: "home_command_center", top_signal_type: "manual_override",
        metadata_json: { recommendation_key: item.recommendationKey, current_mode: item.currentMode, suggested_mode: item.suggestedMode, signals: item.signals },
      }).catch(() => undefined);
      setModeRecommendations((prev) => prev.filter((rec) => rec.courseId !== item.courseId));
    } catch (e) { console.warn("[Dashboard] mode recommendation apply failed:", e); } finally {
      setActingModeCourses((prev) => { const next = new Set(prev); next.delete(item.courseId); return next; });
    }
  };

  const dismissModeRecommendation = (item: ModeRecommendation) => {
    snoozeModeRecommendation(item.courseId, item.recommendationKey);
    void logAgentDecision({
      course_id: item.courseId, action: "snooze_mode_recommendation",
      title: `${t("home.modeRecommendations.snooze")} · ${item.courseName}`, reason: item.reason,
      decision_type: "mode_suggestion", source: "home_command_center", top_signal_type: "manual_override",
      metadata_json: { recommendation_key: item.recommendationKey, current_mode: item.currentMode, suggested_mode: item.suggestedMode, signals: item.signals },
    }).catch(() => undefined);
    setModeRecommendations((prev) =>
      prev.filter((rec) => !(rec.courseId === item.courseId && rec.recommendationKey === item.recommendationKey)),
    );
  };

  return {
    router, t, tf, courses, loading, error, health,
    reviewSummaries, notifications, pendingTasks, actingTasks,
    modeRecommendations, actingModeCourses, upcomingDeadlines,
    dailyDigest, knowledgeDensity,
    totalActiveGoals, totalPendingApprovals, totalRunningTasks, totalUrgentReviews,
    actOnTask, applyModeRecommendation, dismissModeRecommendation,
  };
}
