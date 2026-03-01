"use client";

import { useEffect, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { Plus, Brain, Settings, FileText, BarChart3, Goal, Clock3, ShieldAlert, PlayCircle } from "lucide-react";
import { useCourseStore } from "@/store/course";
import { useT } from "@/lib/i18n-context";

/* Color presets for course card icons */
const CARD_COLORS = [
  { bg: "bg-blue-100", text: "text-blue-500" },
  { bg: "bg-green-100", text: "text-green-600" },
  { bg: "bg-amber-100", text: "text-amber-600" },
  { bg: "bg-purple-100", text: "text-purple-600" },
  { bg: "bg-rose-100", text: "text-rose-500" },
];

function getInitials(name: string) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || "")
    .join("");
}

function formatDashboardDate(value?: string | null) {
  if (!value) return "No recent activity";
  return new Date(value).toLocaleDateString();
}

export default function DashboardPage() {
  const router = useRouter();
  const t = useT();
  const { courses, loading, fetchCourses } = useCourseStore();
  const totalActiveGoals = courses.reduce((sum, course) => sum + (course.active_goal_count ?? 0), 0);
  const totalPendingApprovals = courses.reduce((sum, course) => sum + (course.pending_approval_count ?? 0), 0);
  const totalRunningTasks = courses.reduce((sum, course) => sum + (course.pending_task_count ?? 0), 0);
  const lastStudyDay = courses
    .map((course) => course.last_agent_activity_at)
    .filter((value): value is string => Boolean(value))
    .sort((a, b) => (a > b ? -1 : 1))[0] ?? null;

  const shouldShowOnboarding = useSyncExternalStore(
    () => () => {},
    () => {
      if (typeof window === "undefined") return false;
      return !window.localStorage.getItem("opentutor_onboarded");
    },
    () => false,
  );

  useEffect(() => {
    if (shouldShowOnboarding) {
      router.replace("/onboarding");
    }
  }, [shouldShowOnboarding, router]);

  useEffect(() => {
    fetchCourses();
  }, [fetchCourses]);

  return (
    <div className="min-h-screen bg-white">
      <div className="max-w-5xl mx-auto px-12 py-12 flex flex-col gap-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 bg-indigo-600 rounded-md flex items-center justify-center">
              <Brain className="w-4 h-4 text-white" />
            </div>
            <span className="text-lg font-semibold text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
              OpenTutor
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={() => router.push("/analytics")} className="text-gray-500 hover:text-gray-700">
              <BarChart3 className="w-[22px] h-[22px]" />
            </button>
            <button onClick={() => router.push("/settings")} className="text-gray-500 hover:text-gray-700">
              <Settings className="w-[22px] h-[22px]" />
            </button>
          </div>
        </div>

        {/* Title */}
        <div className="flex flex-col gap-2">
          <h1 className="text-[32px] font-semibold tracking-tight text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
            {t("dashboard.title")}
          </h1>
          <p className="text-[15px] text-gray-500 leading-snug">
            Resume goals, approvals, and active agent work across your courses.
          </p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
            <div className="flex items-center gap-2 text-gray-500 text-xs uppercase tracking-wide">
              <Goal className="w-3.5 h-3.5" />
              Active Goals
            </div>
            <div className="mt-2 text-2xl font-semibold text-gray-900">{totalActiveGoals}</div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
            <div className="flex items-center gap-2 text-gray-500 text-xs uppercase tracking-wide">
              <ShieldAlert className="w-3.5 h-3.5" />
              Pending Approvals
            </div>
            <div className="mt-2 text-2xl font-semibold text-gray-900">{totalPendingApprovals}</div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
            <div className="flex items-center gap-2 text-gray-500 text-xs uppercase tracking-wide">
              <PlayCircle className="w-3.5 h-3.5" />
              Running Tasks
            </div>
            <div className="mt-2 text-2xl font-semibold text-gray-900">{totalRunningTasks}</div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
            <div className="flex items-center gap-2 text-gray-500 text-xs uppercase tracking-wide">
              <Clock3 className="w-3.5 h-3.5" />
              Last Study Day
            </div>
            <div className="mt-2 text-sm font-semibold text-gray-900">{formatDashboardDate(lastStudyDay)}</div>
          </div>
        </div>

        {/* Big Create Button */}
        <button
          onClick={() => router.push("/new")}
          className="w-full h-20 bg-indigo-600 rounded-xl flex items-center justify-center gap-3 text-white hover:bg-indigo-700 transition-colors"
        >
          <Plus className="w-[22px] h-[22px]" />
          <span className="text-lg font-semibold" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
            {t("dashboard.create")}
          </span>
        </button>

        {loading && <p className="text-gray-400 text-sm">{t("general.loading")}</p>}

        {/* Existing Projects Label */}
        {courses.length > 0 && (
          <span className="text-sm font-semibold text-gray-400 tracking-wider uppercase" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
            Existing Projects
          </span>
        )}

        {/* Project Cards */}
        {courses.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {courses.map((course, idx) => {
              const color = CARD_COLORS[idx % CARD_COLORS.length];
              const initials = getInitials(course.name);
              return (
                <button
                  key={course.id}
                  onClick={() => router.push(`/course/${course.id}`)}
                  className="p-6 border border-gray-200 rounded-xl flex flex-col gap-4 text-left hover:border-indigo-600 hover:shadow-md transition-all group"
                >
                  <div className="flex items-center gap-3 w-full">
                    <div className={`w-10 h-10 ${color.bg} rounded-lg flex items-center justify-center shrink-0`}>
                      <span className={`font-bold text-sm ${color.text}`} style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                        {initials}
                      </span>
                    </div>
                    <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                      <span className="font-semibold text-base text-gray-900 truncate" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                        {course.name}
                      </span>
                      <span className="text-xs text-gray-400">
                        Updated: {formatDashboardDate(course.updated_at ?? course.created_at)}
                      </span>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-xs text-gray-500">
                    <div className="flex items-center gap-1">
                      <FileText className="w-3.5 h-3.5 text-gray-400" />
                      <span>{course.file_count ?? 0} files</span>
                    </div>
                    <span>{course.active_goal_count ?? 0} active goals</span>
                    <span>{course.pending_task_count ?? 0} running tasks</span>
                    <span>{course.pending_approval_count ?? 0} approvals</span>
                  </div>
                  <div className="text-xs text-gray-500">
                    {course.description || `Scene: ${course.last_scene_id || "study_session"}`}
                  </div>
                  <span
                    className={`inline-flex w-fit rounded-full px-2.5 py-1 text-xs font-medium ${
                      (course.pending_approval_count ?? 0) > 0
                        ? "bg-amber-50 text-amber-700"
                        : "bg-indigo-50 text-indigo-700"
                    }`}
                  >
                    {(course.pending_approval_count ?? 0) > 0 ? "Resume approval flow" : "Resume work"}
                  </span>
                </button>
              );
            })}
          </div>
        )}

        {/* Empty State */}
        {!loading && courses.length === 0 && (
          <div className="text-center py-16">
            <Brain className="w-12 h-12 mx-auto text-gray-300 mb-4" />
            <h2 className="text-lg font-medium text-gray-900 mb-2">{t("dashboard.empty")}</h2>
          </div>
        )}
      </div>
    </div>
  );
}
