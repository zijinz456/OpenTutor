"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useCourseStore } from "@/store/course";
import {
  getHealthStatus,
  getCourseProgress,
  getReviewSession,
  listNotifications,
  type HealthStatus,
  type AppNotification,
} from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import { useT, useTF } from "@/lib/i18n-context";
import { initStudyNotifications } from "@/lib/study-notifications";
import type { CourseProgressSummary, ReviewSummary } from "../_components/dashboard-utils";

/**
 * Dashboard data: health, course list, due reviews and today's digest.
 * Per-course fan-out is limited to `getReviewSession` + `getCourseProgress`.
 */
export function useDashboardData() {
  const router = useRouter();
  const t = useT();
  const tf = useTF();
  const { courses, loading, error } = useCourseStore();

  const [health, setHealth] = useState<HealthStatus | null>(
    () => ttlCache.get<HealthStatus>("dash:health") ?? null,
  );
  const [reviewSummaries, setReviewSummaries] = useState<ReviewSummary[]>([]);
  const [progressSummaries, setProgressSummaries] = useState<CourseProgressSummary[]>([]);
  const [dailyDigest, setDailyDigest] = useState<AppNotification | null>(null);

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

  // Cross-course review + progress summaries
  useEffect(() => {
    if (courses.length === 0) return;
    let cancelled = false;
    const fetchSummaries = async () => {
      const [reviewResults, progressResults] = await Promise.all([
        Promise.allSettled(
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
        ),
        Promise.allSettled(
          courses.map(async (course) => {
            const progress = await getCourseProgress(course.id);
            return {
              courseId: course.id,
              courseName: course.name,
              averageMastery: progress.average_mastery ?? 0,
              completionPercent: progress.completion_percent ?? 0,
            } as CourseProgressSummary;
          }),
        ),
      ]);
      if (cancelled) return;
      const summaries = reviewResults
        .filter((r): r is PromiseFulfilledResult<ReviewSummary | null> => r.status === "fulfilled")
        .map((r) => r.value)
        .filter((s): s is ReviewSummary => s !== null);
      summaries.sort((a, b) => b.overdueCount - a.overdueCount);
      setReviewSummaries(summaries);
      setProgressSummaries(
        progressResults
          .filter((r): r is PromiseFulfilledResult<CourseProgressSummary> => r.status === "fulfilled")
          .map((r) => r.value),
      );
    };
    void fetchSummaries();
    return () => { cancelled = true; };
  }, [courses]);

  // Daily digest notification
  useEffect(() => {
    listNotifications({ unreadOnly: false, limit: 20 })
      .then((res) => {
        const digest = (res?.notifications ?? []).find((n) => n.category === "daily_brief");
        if (digest) setDailyDigest(digest);
      })
      .catch((e) => console.error("[Dashboard] notifications fetch failed:", e));
  }, []);

  return {
    router, t, tf, courses, loading, error, health,
    reviewSummaries, progressSummaries, dailyDigest, totalUrgentReviews,
  };
}
