"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useCourseStore } from "@/store/course";
import { WorkspaceHeader } from "@/components/shell/workspace-header";
import { ChatFab } from "@/components/chat/chat-fab";
import { ChatDrawer } from "@/components/chat/chat-drawer";
import { getHealthStatus, type HealthStatus } from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import { AnalyticsSection } from "@/components/sections/analytics-section";
import { ModeSelector } from "@/components/course/mode-selector";
import { useT } from "@/lib/i18n-context";

export default function ProfilePage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const courseId = params.id as string;
  const t = useT();
  const [chatOpen, setChatOpen] = useState(false);
  const [health, setHealth] = useState<HealthStatus | null>(
    () => ttlCache.get<HealthStatus>("course:health") ?? null,
  );

  const { activeCourse, courses, fetchCourses, setActiveCourse } = useCourseStore();

  useEffect(() => {
    if (courses.length === 0) void fetchCourses();
  }, [courses.length, fetchCourses]);

  useEffect(() => {
    const course = courses.find((c) => c.id === courseId);
    if (course) setActiveCourse(course);
  }, [courseId, courses, setActiveCourse]);

  useEffect(() => {
    getHealthStatus()
      .then((d) => { ttlCache.set("course:health", d, 30_000); setHealth(d); })
      .catch((e) => console.error("[Profile] health check failed:", e));
  }, []);

  const course = activeCourse ?? courses.find((c) => c.id === courseId) ?? null;
  const aiActionsEnabled =
    health?.llm_status !== "mock_fallback" &&
    health?.llm_status !== "configuration_required";
  const requestedTab = searchParams.get("tab");
  const tab = (requestedTab &&
    ["progress", "review", "blindspots", "forecast", "graph", "agent", "profile"].includes(requestedTab)
      ? requestedTab
      : "profile") as "progress" | "review" | "blindspots" | "forecast" | "graph" | "agent" | "profile";

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <WorkspaceHeader courseName={course?.name || t("course.profile")} courseId={courseId} />
      <main className="flex-1 max-w-5xl mx-auto w-full px-4 py-6 space-y-6">
        {/* Mode selection section */}
        <section className="rounded-2xl bg-card card-shadow p-5">
          <h2 className="text-sm font-semibold text-foreground mb-1">{t("mode.title")}</h2>
          <p className="text-xs text-muted-foreground mb-3">{t("mode.description")}</p>
          <ModeSelector />
        </section>

        {/* Full analytics view with mode-aware default tab */}
        <div className="rounded-2xl bg-card card-shadow overflow-hidden min-h-[380px]">
          <AnalyticsSection courseId={courseId} defaultTab={tab} />
        </div>
      </main>
      <ChatFab open={chatOpen} onToggle={() => setChatOpen((v) => !v)} />
      <ChatDrawer courseId={courseId} open={chatOpen} aiActionsEnabled={aiActionsEnabled} />
    </div>
  );
}
