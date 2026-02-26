"use client";

import { useEffect, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { Plus, Brain, Settings, FileText, RefreshCw, TriangleAlert } from "lucide-react";
import { useCourseStore } from "@/store/course";

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

export default function DashboardPage() {
  const router = useRouter();
  const { courses, loading, fetchCourses } = useCourseStore();

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
          <button onClick={() => router.push("/settings")} className="text-gray-500 hover:text-gray-700">
            <Settings className="w-[22px] h-[22px]" />
          </button>
        </div>

        {/* Title */}
        <div className="flex flex-col gap-2">
          <h1 className="text-[32px] font-semibold tracking-tight text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
            My Learning Spaces
          </h1>
          <p className="text-[15px] text-gray-500 leading-snug">
            Upload learning materials and let Agent create your personalized study experience.
          </p>
        </div>

        {/* Big Create Button */}
        <button
          onClick={() => router.push("/new")}
          className="w-full h-20 bg-indigo-600 rounded-xl flex items-center justify-center gap-3 text-white hover:bg-indigo-700 transition-colors"
        >
          <Plus className="w-[22px] h-[22px]" />
          <span className="text-lg font-semibold" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
            Create New Project
          </span>
        </button>

        {loading && <p className="text-gray-400 text-sm">Loading courses...</p>}

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
                        Last studied: {new Date(course.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                  <div className="flex gap-4">
                    <div className="flex items-center gap-1">
                      <FileText className="w-3.5 h-3.5 text-gray-400" />
                      <span className="text-xs text-gray-500">{course.description || "0 files"}</span>
                    </div>
                  </div>
                  <div className="flex gap-1.5">
                    <span className="px-2 py-1 bg-indigo-50 text-indigo-600 text-[11px] font-medium rounded">Notes</span>
                    <span className="px-2 py-1 bg-indigo-50 text-indigo-600 text-[11px] font-medium rounded">Quiz</span>
                    <span className="px-2 py-1 bg-indigo-50 text-indigo-600 text-[11px] font-medium rounded">Chat</span>
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {/* Auto-Scrape Status */}
        {courses.length > 0 && (
          <div className="p-5 bg-gray-50 border border-gray-200 rounded-xl flex flex-col gap-3">
            <span className="text-[13px] font-semibold text-gray-400 tracking-wider uppercase" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
              Auto-Scrape Status
            </span>
            <div className="flex items-center gap-2">
              <RefreshCw className="w-3.5 h-3.5 text-indigo-600" />
              <span className="text-[13px] text-gray-500">
                {courses[0]?.name} — Last scraped 1h ago, next in 6h
              </span>
            </div>
            {courses.length > 1 && (
              <div className="flex items-center gap-2">
                <TriangleAlert className="w-3.5 h-3.5 text-amber-500" />
                <span className="text-[13px] text-amber-600">
                  {courses[1]?.name} — Session expired, please re-login
                </span>
                <button className="px-3 py-1 border border-gray-200 bg-white text-xs text-indigo-600 font-medium rounded hover:bg-gray-50">
                  Re-login
                </button>
              </div>
            )}
          </div>
        )}

        {/* Empty State */}
        {!loading && courses.length === 0 && (
          <div className="text-center py-16">
            <Brain className="w-12 h-12 mx-auto text-gray-300 mb-4" />
            <h2 className="text-lg font-medium text-gray-900 mb-2">No courses yet</h2>
            <p className="text-gray-400 mb-4">
              Create a project and upload your learning materials to get started.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
