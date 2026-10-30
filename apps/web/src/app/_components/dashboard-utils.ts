import type { Course } from "@/lib/api";
import type { LearningMode } from "@/lib/block-system/types";
import { isLearningMode } from "@/lib/block-system/layout-storage";

export const CARD_COLORS = [
  { bg: "bg-brand-muted", text: "text-brand" },
  { bg: "bg-success-muted", text: "text-success" },
  { bg: "bg-warning-muted", text: "text-warning" },
  { bg: "bg-info-muted", text: "text-info" },
];

export function getInitials(name: string) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || "")
    .join("");
}

export function formatDate(value?: string | null) {
  if (!value) return null;
  return new Date(value).toLocaleDateString();
}

/** Learning mode of a course, from the server-persisted layout/metadata. */
export function getCourseMode(course: Course): LearningMode | undefined {
  const metadata = (course.metadata ?? {}) as Record<string, unknown>;
  const layout = metadata.spaceLayout as { mode?: unknown } | undefined;
  const mode = layout?.mode ?? metadata.learning_mode;
  return isLearningMode(mode) ? mode : undefined;
}

export interface ReviewSummary {
  courseId: string;
  courseName: string;
  overdueCount: number;
  urgentCount: number;
  totalCount: number;
}

export interface CourseProgressSummary {
  courseId: string;
  courseName: string;
  averageMastery: number;
  completionPercent: number;
}
