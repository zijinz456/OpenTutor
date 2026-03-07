"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useCourseStore } from "@/store/course";
import { WorkspaceHeader } from "@/components/shell/workspace-header";
import { ChatFab } from "@/components/chat/chat-fab";
import { ChatDrawer } from "@/components/chat/chat-drawer";
import { getHealthStatus, type HealthStatus } from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import { GraphView } from "@/components/sections/analytics/graph-view";

export default function GraphPage() {
  const params = useParams();
  const courseId = params.id as string;
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
      .catch((e) => console.error("[Graph] health check failed:", e));
  }, []);

  const course = activeCourse ?? courses.find((c) => c.id === courseId) ?? null;
  const aiActionsEnabled =
    health?.llm_status !== "mock_fallback" &&
    health?.llm_status !== "configuration_required";

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <WorkspaceHeader courseName={course?.name || "Knowledge Graph"} courseId={courseId} />
      <main className="flex-1 max-w-5xl mx-auto w-full px-4 py-6">
        <div className="h-[calc(100vh-8rem)]">
          <GraphView courseId={courseId} />
        </div>
      </main>
      <ChatFab open={chatOpen} onToggle={() => setChatOpen((v) => !v)} />
      <ChatDrawer courseId={courseId} open={chatOpen} aiActionsEnabled={aiActionsEnabled} />
    </div>
  );
}
