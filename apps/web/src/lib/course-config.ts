import type { CourseMetadata, CourseWorkspaceFeatures } from "@/lib/api";

export const DEFAULT_WORKSPACE_FEATURES: CourseWorkspaceFeatures = {
  notes: true,
  practice: true,
  wrong_answer: true,
  study_plan: true,
  free_qa: true,
};

export function resolveWorkspaceFeatures(
  metadata?: CourseMetadata | null,
): CourseWorkspaceFeatures {
  return {
    ...DEFAULT_WORKSPACE_FEATURES,
    ...(metadata?.workspace_features ?? {}),
  };
}

export function isRightTabEnabled(
  tab: string,
  features: CourseWorkspaceFeatures,
): boolean {
  if (tab === "quiz" || tab === "flashcards") return features.practice;
  if (tab === "review") return features.wrong_answer;
  if (tab === "plan") return features.study_plan;
  return true;
}

export function getDefaultActivityItem(
  features: CourseWorkspaceFeatures,
): string {
  if (features.notes) return "notes";
  if (features.practice) return "practice";
  if (features.free_qa) return "chat";
  return "progress";
}

export function getDefaultMobileTab(
  features: CourseWorkspaceFeatures,
): "chat" | "notes" | "practice" | "pdf" {
  if (features.free_qa) return "chat";
  if (features.notes) return "notes";
  if (features.practice) return "practice";
  return "pdf";
}
