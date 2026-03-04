import type { IngestionJobSummary } from "@/lib/api";

export type Mode = "upload" | "url" | "both";
export type Step = "mode" | "upload" | "parsing" | "features";

export const STEP_LABELS: { key: Step; labelKey: string }[] = [
  { key: "mode", labelKey: "new.step.source" },
  { key: "upload", labelKey: "new.step.content" },
  { key: "parsing", labelKey: "new.step.parse" },
  { key: "features", labelKey: "new.step.features" },
];

export interface FileItem {
  file: File;
  name: string;
  size: string;
}

export interface ParseStep {
  label: string;
  status: "waiting" | "active" | "done";
}

export interface ParseLog {
  text: string;
  color: string;
}

/* Canvas URL detection -- ported from learning-agent-extension */
const CANVAS_URL_PATTERNS = [
  /^https?:\/\/canvas\.[^/]*\.edu/i,
  /^https?:\/\/[^/]*\.edu\/.*canvas/i,
  /^https?:\/\/[^/]*\.instructure\.com/i,
  /^https?:\/\/[^/]*\.canvaslms\.com/i,
  /^https?:\/\/canvas\.lms\.[^/]+\.edu/i,
];

export function isCanvasUrl(url: string): boolean {
  return CANVAS_URL_PATTERNS.some((p) => p.test(url));
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1048576).toFixed(1) + " MB";
}

/* ---------- Parsing helpers ---------- */

const PARSE_STEPS: { key: string; labelKey: string }[] = [
  { key: "uploaded", labelKey: "new.parse.uploaded" },
  { key: "extracting", labelKey: "new.parse.extracting" },
  { key: "classifying", labelKey: "new.parse.classifying" },
  { key: "dispatching", labelKey: "new.parse.dispatching" },
  { key: "embedding", labelKey: "new.parse.embedding" },
];

const PHASE_ORDER = {
  uploaded: 0,
  extracting: 1,
  classifying: 2,
  dispatching: 3,
  embedding: 4,
  completed: 5,
  failed: 5,
} as const;

function getPhaseRank(status: string): number {
  return PHASE_ORDER[status as keyof typeof PHASE_ORDER] ?? -1;
}

export function deriveParseSteps(
  jobs: IngestionJobSummary[],
  isSubmittingContent: boolean,
  noSourcesSubmitted: boolean,
  t: (key: string) => string,
): ParseStep[] {
  if (noSourcesSubmitted) {
    return PARSE_STEPS.map((step) => ({ label: t(step.labelKey), status: "done" }));
  }
  if (!jobs.length) {
    return PARSE_STEPS.map((step, index) => ({
      label: t(step.labelKey),
      status: isSubmittingContent && index === 0 ? "active" : "waiting",
    }));
  }

  return PARSE_STEPS.map((step, index) => {
    const hasCurrent = jobs.some((job) => job.status === step.key);
    const hasReachedLater = jobs.some((job) => getPhaseRank(job.status) > index);
    const hasReachedCurrent = jobs.some((job) => getPhaseRank(job.status) >= index);

    let status: ParseStep["status"] = "waiting";
    if (hasCurrent) {
      status = "active";
    } else if (hasReachedLater || (hasReachedCurrent && jobs.every((job) => getPhaseRank(job.status) >= index || job.status === "failed"))) {
      status = "done";
    }
    return { label: t(step.labelKey), status };
  });
}

export function deriveParseProgress(
  jobs: IngestionJobSummary[],
  isSubmittingContent: boolean,
  noSourcesSubmitted: boolean,
): number {
  if (noSourcesSubmitted) return 100;
  if (!jobs.length) return isSubmittingContent ? 10 : 0;
  return Math.max(
    5,
    Math.min(
      100,
      Math.round(jobs.reduce((sum, job) => sum + (job.progress_percent ?? 0), 0) / jobs.length),
    ),
  );
}

/* ---------- Feature cards ---------- */

export const FEATURE_CARDS: { id: string; labelKey: string; descriptionKey: string; enabled: boolean; phase?: string }[] = [
  { id: "notes", labelKey: "new.notesFeature", descriptionKey: "new.notesFeatureDesc", enabled: true },
  { id: "practice", labelKey: "new.practiceFeature", descriptionKey: "new.practiceFeatureDesc", enabled: true },
  { id: "wrong_answer", labelKey: "new.reviewFeature", descriptionKey: "new.reviewFeatureDesc", enabled: true },
  { id: "study_plan", labelKey: "new.planFeature", descriptionKey: "new.planFeatureDesc", enabled: true },
  { id: "free_qa", labelKey: "new.qaFeature", descriptionKey: "new.qaFeatureDesc", enabled: true },
];
