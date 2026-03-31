import { setPreference } from "@/lib/api";
import { persistCourseSpaceLayoutLocally } from "@/lib/block-system/layout-sync";
import { useWorkspaceStore } from "@/store/workspace";
import { TEMPLATES } from "@/lib/block-system/templates";
import { isCanvasUrl, type Mode } from "../new/types";
import { buildMetadata } from "../new/parse-actions";
import type { LearningMode, SpaceLayout, BlockInstance } from "@/lib/block-system/types";
import type { SpaceLayoutResponse } from "@/lib/api/onboarding";

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
const DEFAULT_PREFERENCES: Array<[string, string, string]> = [
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

/** Convert an interview-recommended layout to a SpaceLayout. */
function interviewLayoutToSpaceLayout(recommended: SpaceLayoutResponse): SpaceLayout {
  const blocks: BlockInstance[] = recommended.blocks.map((b, i) => ({
    id: `interview-${b.type}-${i}`,
    type: b.type as BlockInstance["type"],
    position: b.position,
    size: b.size as BlockInstance["size"],
    config: b.config,
    visible: b.visible,
    source: (b.source === "onboarding" ? "template" : b.source) as BlockInstance["source"],
  }));
  return {
    templateId: recommended.templateId,
    blocks,
    columns: recommended.columns as SpaceLayout["columns"],
    mode: recommended.mode as LearningMode,
  };
}

/** Persist workspace layout to localStorage after template/mode selection. */
export function persistWorkspaceLayout(
  createdCourseId: string,
  selectedTemplate: string | null,
  selectedMode: LearningMode | null,
  interviewLayout?: SpaceLayoutResponse | null,
) {
  const store = useWorkspaceStore.getState();

  if (interviewLayout) {
    // Apply AI-recommended layout from onboarding interview
    store.loadBlocks(interviewLayoutToSpaceLayout(interviewLayout));
  } else if (selectedTemplate) {
    store.applyBlockTemplate(selectedTemplate);
  }
  if (selectedMode) {
    store.setSpaceMode(selectedMode);
  }
  const layout = store.spaceLayout;
  if (selectedTemplate || selectedMode || interviewLayout) {
    persistCourseSpaceLayoutLocally(createdCourseId, layout);
  }
  try { localStorage.setItem("opentutor_onboarded", "true"); } catch { /* quota */ }
}
