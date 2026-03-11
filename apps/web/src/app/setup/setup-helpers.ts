import { setPreference } from "@/lib/api";
import { useWorkspaceStore } from "@/store/workspace";
import { updateUnlockContext } from "@/lib/block-system/feature-unlock";
import { TEMPLATES } from "@/lib/block-system/templates";
import { isCanvasUrl, type Mode } from "../new/types";
import { buildMetadata } from "../new/parse-actions";
import type { LearningMode } from "@/lib/block-system/types";

/** Pure name validation — returns error key or null. */
export function validateNameValue(value: string, t: (k: string) => string): string | null {
  if (!value.trim()) return t("new.projectNameRequired");
  if (value.length > 100) return t("new.projectNameTooLong");
  return null;
}

/** Pure URL validation — returns { error, isCanvas }. */
export function validateUrlValue(
  value: string,
  t: (k: string) => string,
): { error: string | null; isCanvas: boolean } {
  const trimmed = value.trim();
  let error: string | null = null;
  if (trimmed && !/^https?:\/\//i.test(trimmed)) {
    error = t("new.urlInvalid");
  }
  const isCanvas = trimmed ? isCanvasUrl(trimmed) : false;
  return { error, isCanvas };
}

/** Default global preferences applied on first workspace entry. */
export const DEFAULT_PREFERENCES: Array<[string, string, string]> = [
  ["language", "auto", "global"],
  ["learning_mode", "balanced", "global"],
  ["detail_level", "balanced", "global"],
  ["layout_preset", "balanced", "global"],
];

/** Set all default preferences (fire-and-forget safe). */
export function applyDefaultPreferences() {
  return Promise.allSettled(
    DEFAULT_PREFERENCES.map(([key, val, scope]) => setPreference(key, val, scope)),
  );
}

/** Build course metadata for a new course. */
export function buildCourseMetadata(
  files: { length: number },
  url: string,
  selectedTemplate: string | null,
  selectedMode: LearningMode | null,
  hasContent = true,
) {
  const features = { notes: true, practice: true, study_plan: true, free_qa: true, wrong_answer: true };
  const sourceMode: Mode = files.length > 0 && url.trim() ? "both" : files.length > 0 ? "upload" : "url";
  const modeFromTemplate = selectedTemplate ? TEMPLATES[selectedTemplate]?.defaultMode : undefined;
  const modeForCourse = selectedMode ?? modeFromTemplate;
  const metadata = {
    ...buildMetadata(features, hasContent, url, sourceMode),
    ...(modeForCourse ? { learning_mode: modeForCourse } : {}),
  };
  return { metadata, sourceMode };
}

/** Persist workspace layout to localStorage after template/mode selection. */
export function persistWorkspaceLayout(
  createdCourseId: string,
  selectedTemplate: string | null,
  selectedMode: LearningMode | null,
) {
  if (selectedTemplate) {
    useWorkspaceStore.getState().applyBlockTemplate(selectedTemplate);
  }
  if (selectedMode) {
    useWorkspaceStore.getState().setSpaceMode(selectedMode);
  }
  const layout = useWorkspaceStore.getState().spaceLayout;
  if (selectedTemplate || selectedMode) {
    try { localStorage.setItem(`opentutor_blocks_${createdCourseId}`, JSON.stringify(layout)); } catch { /* quota */ }
    if (layout.mode) {
      updateUnlockContext(createdCourseId, { mode: layout.mode });
    }
  }
  try { localStorage.setItem("opentutor_onboarded", "true"); } catch { /* quota */ }
}
