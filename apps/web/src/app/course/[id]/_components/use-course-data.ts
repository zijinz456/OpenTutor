"use client";

import { useEffect, useState } from "react";
import { useCourseStore } from "@/store/course";
import { getHealthStatus, type HealthStatus } from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import { incrementSessionCount } from "@/lib/block-system/feature-unlock";
import { recordSessionVisit } from "@/lib/learner-persona";

export function useCourseData(courseId: string) {
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
    incrementSessionCount(courseId);
    recordSessionVisit();
  }, [courseId]);

  const course = activeCourse ?? courses.find((item) => item.id === courseId) ?? null;
  const aiActionsEnabled =
    health?.llm_status !== "mock_fallback" &&
    health?.llm_status !== "configuration_required";

  return { health, course, courses, contentTree, aiActionsEnabled };
}
