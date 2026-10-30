"use client";

import type { ReactNode } from "react";
import { useParams } from "next/navigation";
import { CourseProvider } from "./_hooks/course-context";

/**
 * Owns the shared course bootstrap (course list, active course, content tree,
 * health check, unlock signals) for every `/course/[id]/*` page.
 */
export default function CourseLayout({ children }: { children: ReactNode }) {
  const params = useParams();
  const courseId = params.id as string;
  return <CourseProvider courseId={courseId}>{children}</CourseProvider>;
}
