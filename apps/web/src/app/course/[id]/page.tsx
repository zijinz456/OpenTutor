"use client";

import { useEffect } from "react";
import { useParams } from "next/navigation";
import { useCourseStore } from "@/store/course";
import { useChatStore } from "@/store/chat";
import { useSceneStore } from "@/store/scene";
import { AppShell } from "@/components/shell/app-shell";
import { WorkspaceHeader } from "@/components/shell/workspace-header";
import { CourseTree } from "@/components/course-tree/course-tree";
import { ChatView } from "@/components/chat/chat-view";
import { SectionContainer } from "@/components/sections/section-container";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";

export default function CoursePage() {
  const params = useParams();
  const courseId = params.id as string;

  const { activeCourse, setActiveCourse, courses, fetchCourses, fetchIngestionJobs } =
    useCourseStore();
  const { fetchScenes, fetchActiveScene } = useSceneStore();

  // Register global keyboard shortcuts
  useKeyboardShortcuts();

  // Load course data on mount
  useEffect(() => {
    if (courses.length === 0) fetchCourses();
  }, [courses.length, fetchCourses]);

  // Set active course when courses are loaded
  useEffect(() => {
    const course = courses.find((c) => c.id === courseId);
    if (course) setActiveCourse(course);
  }, [courseId, courses, setActiveCourse]);

  // Load scenes (content tree is loaded by setActiveCourse in the course store)
  useEffect(() => {
    fetchScenes();
    fetchActiveScene(courseId);
  }, [courseId, fetchScenes, fetchActiveScene]);

  // Load ingestion jobs (file list with categories)
  useEffect(() => {
    fetchIngestionJobs(courseId);
  }, [courseId, fetchIngestionJobs]);

  // Auto-send init prompt if present in localStorage
  useEffect(() => {
    const promptKey = `course_init_prompt_${courseId}`;
    const consumedKey = `course_init_prompt_consumed_${courseId}`;
    const initPrompt = localStorage.getItem(promptKey);
    const alreadyConsumed = sessionStorage.getItem(consumedKey) === "true";
    if (initPrompt && !alreadyConsumed) {
      sessionStorage.setItem(consumedKey, "true");
      localStorage.removeItem(promptKey);
      const timer = setTimeout(() => {
        const scene = useSceneStore.getState().activeScene;
        void useChatStore.getState().sendMessage(courseId, initPrompt, { scene });
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [courseId]);

  return (
    <div className="h-screen flex flex-col bg-background">
      <WorkspaceHeader
        courseId={courseId}
        courseName={activeCourse?.name || "Course"}
      />
      <AppShell
        courseId={courseId}
        tree={<CourseTree courseId={courseId} />}
        chat={<ChatView courseId={courseId} />}
      >
        <SectionContainer courseId={courseId} />
      </AppShell>
    </div>
  );
}
