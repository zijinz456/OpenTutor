"use client";

import { useEffect, useMemo } from "react";
import { useParams } from "next/navigation";
import { useCourseStore } from "@/store/course";
import { useChatStore } from "@/store/chat";
import { useWorkspaceStore, type SectionId } from "@/store/workspace";
import { resolveWorkspaceFeatures } from "@/lib/course-config";
import { AppShell } from "@/components/shell/app-shell";
import { WorkspaceHeader } from "@/components/shell/workspace-header";
import { CourseTree } from "@/components/course-tree/course-tree";
import { ChatView } from "@/components/chat/chat-view";
import { SectionContainer } from "@/components/sections/section-container";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";

export default function CoursePage() {
  const params = useParams();
  const courseId = params.id as string;

  const {
    activeCourse,
    setActiveCourse,
    courses,
    fetchCourses,
    fetchIngestionJobs,
  } = useCourseStore();
  const activeSection = useWorkspaceStore((s) => s.activeSection);
  const setActiveSection = useWorkspaceStore((s) => s.setActiveSection);

  useKeyboardShortcuts();

  useEffect(() => {
    if (courses.length === 0) {
      void fetchCourses();
    }
  }, [courses.length, fetchCourses]);

  useEffect(() => {
    const course = courses.find((c) => c.id === courseId);
    if (course) {
      setActiveCourse(course);
    }
  }, [courseId, courses, setActiveCourse]);

  useEffect(() => {
    void fetchIngestionJobs(courseId);
  }, [courseId, fetchIngestionJobs]);

  const course = activeCourse ?? courses.find((item) => item.id === courseId) ?? null;

  const features = useMemo(
    () => resolveWorkspaceFeatures(course?.metadata),
    [course?.metadata],
  );

  const visibleSections = useMemo<SectionId[]>(
    () => [
      ...(features.notes ? (["notes"] as const) : []),
      ...(features.practice ? (["practice"] as const) : []),
      "analytics",
      ...(features.study_plan ? (["plan"] as const) : []),
    ],
    [features.notes, features.practice, features.study_plan],
  );

  useEffect(() => {
    if (course && visibleSections.length > 0) {
      setActiveSection(visibleSections[0]);
    }
  }, [course, courseId, setActiveSection, visibleSections]);

  useEffect(() => {
    if (!course || visibleSections.length === 0) {
      return;
    }
    if (!visibleSections.includes(activeSection)) {
      setActiveSection(visibleSections[0]);
    }
  }, [activeSection, course, setActiveSection, visibleSections]);

  useEffect(() => {
    const promptKey = `course_init_prompt_${courseId}`;
    const consumedKey = `course_init_prompt_consumed_${courseId}`;
    const initPrompt = localStorage.getItem(promptKey);
    const alreadyConsumed = sessionStorage.getItem(consumedKey) === "true";
    if (initPrompt && !alreadyConsumed) {
      sessionStorage.setItem(consumedKey, "true");
      localStorage.removeItem(promptKey);
      const timer = setTimeout(() => {
        void useChatStore.getState().sendMessage(courseId, initPrompt);
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [courseId]);

  return (
    <div className="h-screen flex flex-col bg-background">
      <WorkspaceHeader courseName={course?.name || "Course"} />
      <AppShell
        courseId={courseId}
        tree={<CourseTree courseId={courseId} />}
        chat={features.free_qa ? <ChatView courseId={courseId} /> : undefined}
      >
        <SectionContainer
          courseId={courseId}
          visibleSections={visibleSections}
          chatEnabled={features.free_qa}
          reviewEnabled={features.wrong_answer}
        />
      </AppShell>
    </div>
  );
}
