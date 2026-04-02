"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useCourseStore } from "@/store/course";
import { useWorkspaceStore } from "@/store/workspace";
import { WorkspaceHeader } from "@/components/shell/workspace-header";
import { PlanSection } from "@/components/sections/plan-section";
import { ChatFab } from "@/components/chat/chat-fab";
import { ChatDrawer } from "@/components/chat/chat-drawer";
import { getHealthStatus, type HealthStatus } from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import type { LearningMode } from "@/lib/block-system/types";
import { getStoredSpaceLayoutMode } from "@/lib/block-system/layout-storage";

function asLearningMode(value: unknown): LearningMode | undefined {
  return value === "course_following" ||
    value === "self_paced" ||
    value === "exam_prep" ||
    value === "maintenance"
    ? value
    : undefined;
}

export default function PlanPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const courseId = params.id as string;
  const [chatOpen, setChatOpen] = useState(false);
  const [health, setHealth] = useState<HealthStatus | null>(
    () => ttlCache.get<HealthStatus>("course:health") ?? null,
  );

  const { activeCourse, courses, fetchCourses, setActiveCourse } = useCourseStore();
  const spaceMode = useWorkspaceStore((s) => s.spaceLayout.mode);

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
      .catch((e) => console.error("[Plan] health check failed:", e));
  }, []);

  const course = activeCourse ?? courses.find((c) => c.id === courseId) ?? null;
  const resolvedMode = useMemo(() => {
    const metadata = (course?.metadata as Record<string, unknown> | undefined) ?? {};
    const layout = metadata.spaceLayout;
    const layoutMode = layout && typeof layout === "object"
      ? asLearningMode((layout as Record<string, unknown>).mode)
      : undefined;
    const metaMode = asLearningMode(metadata.learning_mode);
    const localMode = typeof window !== "undefined" ? getStoredSpaceLayoutMode(courseId) : undefined;

    return spaceMode ?? localMode ?? layoutMode ?? metaMode;
  }, [course?.metadata, courseId, spaceMode]);

  const requestedTab = searchParams.get("tab");
  const defaultTab =
    requestedTab === "plan" || requestedTab === "calendar" || requestedTab === "tasks" || requestedTab === "timeline"
      ? requestedTab
      : undefined;

  const aiActionsEnabled =
    health?.llm_status !== "mock_fallback" &&
    health?.llm_status !== "configuration_required";

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <WorkspaceHeader courseName={course?.name || "Study Plan"} courseId={courseId} />
      <main className="flex-1 max-w-5xl mx-auto w-full px-4 py-6">
        <PlanSection
          courseId={courseId}
          aiActionsEnabled={aiActionsEnabled}
          learningMode={resolvedMode}
          defaultTab={defaultTab}
        />
      </main>
      <ChatFab open={chatOpen} onToggle={() => setChatOpen((v) => !v)} />
      <ChatDrawer courseId={courseId} open={chatOpen} aiActionsEnabled={aiActionsEnabled} />
    </div>
  );
}
