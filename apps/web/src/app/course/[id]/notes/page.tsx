"use client";

import { NotesSection } from "@/components/sections/notes-section";
import { useT } from "@/lib/i18n-context";
import { CoursePageFrame } from "../_components/course-page-frame";
import { useCourseContext } from "../_hooks/course-context";

export default function NotesPage() {
  const t = useT();
  const { courseId, aiActionsEnabled } = useCourseContext();

  return (
    <CoursePageFrame title={t("course.notes")}>
      <NotesSection courseId={courseId} aiActionsEnabled={aiActionsEnabled} />
    </CoursePageFrame>
  );
}
