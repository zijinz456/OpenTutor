"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useCourseStore } from "@/store/course";
import { getHealthStatus, getLearningProfile, type HealthStatus } from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import { useLocale, useT } from "@/lib/i18n-context";
import { RuntimeAlert } from "@/components/shared/runtime-alert";

const REQUIRED_ONBOARDING_DIMENSIONS = [
  "language",
  "learning_mode",
  "detail_level",
  "layout_preset",
] as const;

const CARD_COLORS = [
  { bg: "bg-brand-muted", text: "text-brand" },
  { bg: "bg-success-muted", text: "text-success" },
  { bg: "bg-warning-muted", text: "text-warning" },
  { bg: "bg-info-muted", text: "text-info" },
];

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

export default function DashboardPage() {
  const router = useRouter();
  const t = useT();
  const { locale, setLocale } = useLocale();
  const { courses, loading, error } = useCourseStore();
  const totalActiveGoals = courses.reduce((sum, c) => sum + (c.active_goal_count ?? 0), 0);
  const totalPendingApprovals = courses.reduce((sum, c) => sum + (c.pending_approval_count ?? 0), 0);
  const totalRunningTasks = courses.reduce((sum, c) => sum + (c.pending_task_count ?? 0), 0);

  const [health, setHealth] = useState<HealthStatus | null>(
    () => ttlCache.get<HealthStatus>("dash:health") ?? null,
  );

  // Onboarding check
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.localStorage.getItem("opentutor_onboarded")) return;

    getLearningProfile()
      .then((profile) => {
        const completed = REQUIRED_ONBOARDING_DIMENSIONS.every((dim) =>
          profile.preferences.some((p) => p.scope === "global" && p.dimension === dim),
        );
        if (completed) {
          window.localStorage.setItem("opentutor_onboarded", "true");
          const langPref = profile.preferences.find(
            (p) => p.scope === "global" && p.dimension === "language" && (p.value === "en" || p.value === "zh"),
          );
          if (langPref?.value === "en" || langPref?.value === "zh") setLocale(langPref.value);
        } else {
          router.replace("/onboarding");
        }
      })
      .catch(() => router.replace("/onboarding"));
  }, [router, setLocale]);

  // Load courses and health (poll every 30s for live status)
  useEffect(() => {
    useCourseStore.getState().fetchCourses();
    const refreshHealth = () =>
      getHealthStatus()
        .then((d) => { ttlCache.set("dash:health", d, 30_000); setHealth(d); })
        .catch(() => {});
    refreshHealth();
    const id = setInterval(refreshHealth, 30_000);
    return () => clearInterval(id);
  }, []);

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
              onClick={() => router.push("/settings")}
              className="px-3 py-2 rounded-md text-sm text-sidebar-foreground hover:bg-sidebar-accent transition-colors text-left"
            >
              {t("nav.settings")}
            </button>
          </nav>
          {health?.deployment_mode === "single_user" && (
            <span className="mt-3 inline-flex w-fit rounded-md bg-muted px-3 py-1.5 text-center text-[11px] font-medium text-muted-foreground md:mt-auto">
              {t("dashboard.singleUser")}
            </span>
          )}
        </aside>

        {/* Main Content */}
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-6 sm:px-6 md:px-10 md:py-10">
            <RuntimeAlert health={health} />

            {error && (
              <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                {t("dashboard.loadErrorPrefix")}: {error}
              </div>
            )}

            {/* Title + New Project */}
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div className="flex flex-col gap-1">
                <h1 className="text-2xl font-semibold tracking-tight text-foreground">
                  {t("dashboard.title")}
                </h1>
                <p className="text-sm text-muted-foreground">
                  {t("dashboard.subtitle")}
                </p>
              </div>
              <div className="flex items-center gap-2 self-start sm:self-auto">
                <button
                  onClick={() => router.push("/new")}
                  className="h-9 px-5 bg-brand text-brand-foreground rounded-lg text-sm font-medium hover:opacity-90 transition-opacity shrink-0"
                >
                  + {t("dashboard.create")}
                </button>
              </div>
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

            {/* Course list */}
            {loading && <CourseCardsSkeleton />}

            {courses.length > 0 && (
              <div className="flex flex-col gap-4">
                <span className="text-xs font-semibold text-muted-foreground tracking-wider uppercase">
                  {t("dashboard.existingProjects")}
                </span>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {courses.map((course, idx) => {
                    const color = CARD_COLORS[idx % CARD_COLORS.length];
                    const initials = getInitials(course.name);
                    const hasPending = (course.pending_approval_count ?? 0) > 0;
                    return (
                      <button
                        key={course.id}
                        onClick={() => router.push(`/course/${course.id}`)}
                        className="p-5 border border-border rounded-xl flex flex-col gap-3 text-left hover:border-brand hover:shadow-sm transition-all bg-card"
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
                        <div className="text-xs text-muted-foreground line-clamp-1">
                          {course.description || `${t("dashboard.scenePrefix")}: ${course.last_scene_id || "study_session"}`}
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
          </div>
        </main>
      </div>
    </div>
  );
}
