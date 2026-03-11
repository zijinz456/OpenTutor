"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useCourseStore } from "@/store/course";
import { WorkspaceHeader } from "@/components/shell/workspace-header";
import { PracticeSection } from "@/components/sections/practice-section";
import { ChatFab } from "@/components/chat/chat-fab";
import { ChatDrawer } from "@/components/chat/chat-drawer";
import { getHealthStatus, type HealthStatus } from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import { useT } from "@/lib/i18n-context";

export default function PracticePage() {
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
      .catch((e) => console.error("[Practice] health check failed:", e));
  }, []);

  const course = activeCourse ?? courses.find((c) => c.id === courseId) ?? null;
  const aiActionsEnabled =
    health?.llm_status !== "mock_fallback" &&
    health?.llm_status !== "configuration_required";
  const tab = (searchParams.get("tab") ?? "quiz") as "quiz" | "flashcards" | "review";
  const difficultyParam = searchParams.get("difficulty");
  const modeParam = searchParams.get("mode");
  const quizDifficultyHint =
    difficultyParam === "easy" || difficultyParam === "medium" || difficultyParam === "hard"
      ? difficultyParam
      : undefined;
  const quizModeHint =
    modeParam === "course_following" ||
    modeParam === "self_paced" ||
    modeParam === "exam_prep" ||
    modeParam === "maintenance"
      ? modeParam
      : undefined;

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <WorkspaceHeader courseName={course?.name || t("course.practice")} courseId={courseId} />
      <main className="flex-1 max-w-5xl mx-auto w-full px-4 py-6">
        <PracticeSection
          courseId={courseId}
          showReview
          aiActionsEnabled={aiActionsEnabled}
          defaultTab={tab}
          quizDifficultyHint={quizDifficultyHint}
          quizModeHint={quizModeHint}
        />
      </main>
      <ChatFab open={chatOpen} onToggle={() => setChatOpen((v) => !v)} />
      <ChatDrawer courseId={courseId} open={chatOpen} aiActionsEnabled={aiActionsEnabled} />
    </div>
  );
}
