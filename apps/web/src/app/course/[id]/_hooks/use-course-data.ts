"use client";

import { useEffect, useState } from "react";
import { useCourseStore } from "@/store/course";
import { getHealthStatus, type Course, type ContentNode, type HealthStatus } from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import { refreshUnlockSignals } from "@/lib/block-system/feature-unlock";
import { recordSessionVisit } from "@/lib/learner-persona";

export interface CourseData {
  health: HealthStatus | null;
  course: Course | null;
  courses: Course[];
  contentTree: ContentNode[];
  aiActionsEnabled: boolean;
}

/**
 * Shared course bootstrap: loads the course list, marks the active course,
 * fetches the content tree + ingestion jobs, checks runtime health and
 * refreshes the server-derived feature-unlock signals.
 *
 * Mounted once by `app/course/[id]/layout.tsx`; sub-pages read the result
 * through `useCourseContext()`.
 */
export function useCourseData(courseId: string): CourseData {
  const [health, setHealth] = useState<HealthStatus | null>(
    () => ttlCache.get<HealthStatus>("course:health") ?? null,
  );

  // Use granular selectors to avoid re-rendering on every store change
  const activeCourse = useCourseStore((s) => s.activeCourse);
  const courses = useCourseStore((s) => s.courses);
  const contentTree = useCourseStore((s) => s.contentTree);
  const fetchCourses = useCourseStore((s) => s.fetchCourses);
  const setActiveCourse = useCourseStore((s) => s.setActiveCourse);
  const fetchContentTree = useCourseStore((s) => s.fetchContentTree);
  const fetchIngestionJobs = useCourseStore((s) => s.fetchIngestionJobs);

  useEffect(() => {
    if (courses.length === 0) void fetchCourses();
  }, [courses.length, fetchCourses]);

  useEffect(() => {
    const course = courses.find((c) => c.id === courseId);
    if (course) setActiveCourse(course);
  }, [courseId, courses, setActiveCourse]);

  useEffect(() => {
    void fetchContentTree(courseId);
    void fetchIngestionJobs(courseId);
  }, [courseId, fetchContentTree, fetchIngestionJobs]);

  useEffect(() => {
    getHealthStatus()
      .then((data) => {
        ttlCache.set("course:health", data, 30_000);
        setHealth(data);
      })
      .catch((e) => console.error("[Course] health check failed:", e));
  }, []);

  useEffect(() => {
    void refreshUnlockSignals(courseId);
    recordSessionVisit();
  }, [courseId]);

  const course = activeCourse ?? courses.find((item) => item.id === courseId) ?? null;
  const aiActionsEnabled =
    health?.llm_status !== "mock_fallback" &&
    health?.llm_status !== "configuration_required";

  return { health, course, courses, contentTree, aiActionsEnabled };
}
