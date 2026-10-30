"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useCourseData, type CourseData } from "./use-course-data";

export interface CourseContextValue extends CourseData {
  courseId: string;
}

const CourseContext = createContext<CourseContextValue | null>(null);

export function CourseProvider({ courseId, children }: { courseId: string; children: ReactNode }) {
  const data = useCourseData(courseId);
  return (
    <CourseContext.Provider value={{ courseId, ...data }}>
      {children}
    </CourseContext.Provider>
  );
}

/** Course bootstrap data owned by `app/course/[id]/layout.tsx`. */
export function useCourseContext(): CourseContextValue {
  const ctx = useContext(CourseContext);
  if (!ctx) {
    throw new Error("useCourseContext must be used inside app/course/[id]/layout.tsx");
  }
  return ctx;
}
