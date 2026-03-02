"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useCourseStore } from "@/store/course";
import { getHealthStatus, getLearningProfile, type HealthStatus } from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import { useLocale, useT } from "@/lib/i18n-context";
import { WeeklyReportCard } from "@/components/weekly-report-card";

const REQUIRED_ONBOARDING_DIMENSIONS = [
  "language",
  "learning_mode",
  "detail_level",
  "layout_preset",
] as const;

/* Color presets for course card initials */
const CARD_COLORS = [
  { bg: "bg-brand-muted", text: "text-brand" },
  { bg: "bg-success-muted", text: "text-success" },
  { bg: "bg-warning-muted", text: "text-warning" },
  { bg: "bg-info-muted", text: "text-info" },
  { bg: "bg-brand-muted", text: "text-brand" },
];

function getInitials(name: string) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || "")
    .join("");
}

function formatDashboardDate(value?: string | null) {
  if (!value) return null;
  return new Date(value).toLocaleDateString();
}

function CourseCardsSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
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

function WeeklyReportSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-muted/50 p-5 animate-pulse">
      <div className="flex items-center justify-between mb-3">
        <div className="h-4 bg-muted rounded w-32" />
        <div className="h-3 bg-muted rounded w-24" />
      </div>
      <div className="grid grid-cols-3 gap-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="space-y-2">
            <div className="h-3 bg-muted rounded w-16" />
            <div className="h-5 bg-muted rounded w-12" />
          </div>
        ))}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const t = useT();
  const { locale, setLocale } = useLocale();
  const { courses, loading, fetchCourses } = useCourseStore();
  const totalActiveGoals = courses.reduce((sum, course) => sum + (course.active_goal_count ?? 0), 0);

  const [health, setHealth] = useState<HealthStatus | null>(() => ttlCache.get<HealthStatus>("dash:health") ?? null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.localStorage.getItem("opentutor_onboarded")) return;

    getLearningProfile()
      .then((profile) => {
        const completed = REQUIRED_ONBOARDING_DIMENSIONS.every((dimension) =>
          profile.preferences.some((preference) => preference.scope === "global" && preference.dimension === dimension),
        );

        if (completed) {
          window.localStorage.setItem("opentutor_onboarded", "true");
          const languagePreference = profile.preferences.find(
            (preference) =>
              preference.scope === "global" &&
              preference.dimension === "language" &&
              (preference.value === "en" || preference.value === "zh"),
          );
          if (languagePreference?.value === "en" || languagePreference?.value === "zh") {
            setLocale(languagePreference.value);
          }
        } else {
          router.replace("/onboarding");
        }
      })
      .catch(() => {
        router.replace("/onboarding");
      });
  }, [router, setLocale]);

  useEffect(() => {
    fetchCourses();

    const DASH_TTL = 120_000;

    if (!health) {
      getHealthStatus()
        .then((d) => { ttlCache.set("dash:health", d, DASH_TTL); setHealth(d); })
        .catch(() => {});
    }
  }, [fetchCourses, health]);

  const totalPendingApprovals = courses.reduce((sum, course) => sum + (course.pending_approval_count ?? 0), 0);
  const totalRunningTasks = courses.reduce((sum, course) => sum + (course.pending_task_count ?? 0), 0);

  return (
    <div className="min-h-screen bg-background">
      {/* Sidebar + Content shell */}
      <div className="flex min-h-screen">
        {/* Left Navigation Sidebar */}
        <aside className="w-[200px] shrink-0 border-r border-border bg-sidebar p-4 flex flex-col gap-6 hidden md:flex">
          <div className="flex items-center gap-2 px-2 py-1">
            <span className="text-base font-bold text-sidebar-foreground tracking-tight">OpenTutor</span>
          </div>
          <nav className="flex flex-col gap-1">
            <span className="px-3 py-2 rounded-md text-sm font-semibold bg-sidebar-accent text-sidebar-accent-foreground">
              {t("nav.dashboard")}
            </span>
            <button
              onClick={() => router.push("/analytics")}
              className="px-3 py-2 rounded-md text-sm text-sidebar-foreground hover:bg-sidebar-accent transition-colors text-left"
            >
              {t("nav.analytics")}
            </button>
            <button
              onClick={() => router.push("/settings")}
              className="px-3 py-2 rounded-md text-sm text-sidebar-foreground hover:bg-sidebar-accent transition-colors text-left"
            >
              {t("nav.settings")}
            </button>
          </nav>
          {health?.deployment_mode === "single_user" && (
            <span className="mt-auto px-3 py-1.5 rounded-md text-[11px] font-medium text-muted-foreground bg-muted text-center">
              {t("dashboard.singleUser")}
            </span>
          )}
        </aside>

        {/* Main Content */}
        <main className="flex-1 overflow-y-auto">
          <div className="max-w-4xl mx-auto px-6 md:px-12 py-10 flex flex-col gap-8">
            {/* Mobile header (sidebar hidden on mobile) */}
            <div className="flex items-center justify-between md:hidden">
              <span className="text-base font-bold text-foreground tracking-tight">OpenTutor</span>
              <div className="flex items-center gap-4">
                <button onClick={() => router.push("/analytics")} className="text-sm text-muted-foreground hover:text-foreground transition-colors">
                  {t("nav.analytics")}
                </button>
                <button onClick={() => router.push("/settings")} className="text-sm text-muted-foreground hover:text-foreground transition-colors">
                  {t("nav.settings")}
                </button>
              </div>
            </div>

            {/* Title + New Project */}
            <div className="flex items-end justify-between gap-4">
              <div className="flex flex-col gap-1">
                <h1 className="text-2xl font-semibold tracking-tight text-foreground">
                  {t("dashboard.title")}
                </h1>
                <p className="text-sm text-muted-foreground">
                  {t("dashboard.subtitle")}
                </p>
              </div>
              <button
                onClick={() => router.push("/new")}
                className="h-9 px-5 bg-brand text-brand-foreground rounded-lg text-sm font-medium hover:opacity-90 transition-opacity shrink-0"
              >
                + {t("dashboard.create")}
              </button>
            </div>

            {/* Overview stats */}
            {courses.length > 0 && (
              <div className="grid grid-cols-3 gap-3">
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

            {/* Weekly Report */}
            <Suspense fallback={<WeeklyReportSkeleton />}>
              <WeeklyReportCard />
            </Suspense>

            {/* Course list */}
            <Suspense fallback={<CourseCardsSkeleton />}>
              {loading && <p className="text-muted-foreground text-sm">{t("general.loading")}</p>}

              {courses.length > 0 && (
                <div className="flex flex-col gap-4">
                  <span className="text-xs font-semibold text-muted-foreground tracking-wider uppercase">
                    {t("dashboard.existingProjects")}
                  </span>

                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {courses.map((course, idx) => {
                      const color = CARD_COLORS[idx % CARD_COLORS.length];
                      const initials = getInitials(course.name);
                      const hasPendingApprovals = (course.pending_approval_count ?? 0) > 0;
                      return (
                        <button
                          key={course.id}
                          onClick={() => router.push(`/course/${course.id}`)}
                          className="p-5 border border-border rounded-xl flex flex-col gap-3 text-left hover:border-brand hover:shadow-sm transition-all bg-card"
                        >
                          <div className="flex items-center gap-3 w-full">
                            <div className={`w-9 h-9 ${color.bg} rounded-lg flex items-center justify-center shrink-0`}>
                              <span className={`font-bold text-xs ${color.text}`}>
                                {initials}
                              </span>
                            </div>
                            <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                              <span className="font-semibold text-sm text-foreground truncate">
                                {course.name}
                              </span>
                              <span className="text-[11px] text-muted-foreground">
                                {formatDashboardDate(course.updated_at ?? course.created_at)}
                              </span>
                            </div>
                          </div>
                          <div className="text-xs text-muted-foreground line-clamp-1">
                            {course.description || `${t("dashboard.scenePrefix")}: ${course.last_scene_id || "study_session"}`}
                          </div>
                          {hasPendingApprovals && (
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
                </div>
              )}

              {/* Empty State */}
              {!loading && courses.length === 0 && (
                <div className="text-center py-20 flex flex-col items-center gap-4">
                  <h2 className="text-lg font-semibold text-foreground">{t("dashboard.empty")}</h2>
                  <p className="text-sm text-muted-foreground max-w-sm">
                    {t("dashboard.emptyDescription")}
                  </p>
                  <button
                    onClick={() => router.push("/new")}
                    className="h-10 px-6 bg-brand text-brand-foreground rounded-lg text-sm font-medium hover:opacity-90 transition-opacity"
                  >
                    {t("dashboard.create")}
                  </button>
                </div>
              )}
            </Suspense>
          </div>
        </main>
      </div>
    </div>
  );
}
