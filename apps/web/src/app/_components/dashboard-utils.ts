import type { Course, AppNotification, AgentTask } from "@/lib/api";
import type { LearningMode, SpaceLayout } from "@/lib/block-system/types";

export const CARD_COLORS = [
  { bg: "bg-brand-muted", text: "text-brand" },
  { bg: "bg-success-muted", text: "text-success" },
  { bg: "bg-warning-muted", text: "text-warning" },
  { bg: "bg-info-muted", text: "text-info" },
];

export function getDashboardNowMs() { return Date.now(); }

export const MODE_REC_SNOOZE_MS = 12 * 60 * 60 * 1000;

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

export function resolveNotificationPath(notification: AppNotification): string | null {
  const actionUrl = notification.action_url?.trim();
  if (actionUrl?.startsWith("/")) return actionUrl;
  const data = notification.data;
  if (!data || typeof data !== "object") return null;
  const candidate = (data as Record<string, unknown>).action_url;
  if (typeof candidate === "string" && candidate.trim().startsWith("/")) {
    return candidate.trim();
  }
  return null;
}

export function notificationMatchesTask(notification: AppNotification, taskId: string): boolean {
  const data = notification.data;
  if (!data || typeof data !== "object") return false;
  const record = data as Record<string, unknown>;
  return record.task_id === taskId ||
    record.queued_task_id === taskId ||
    record.agent_task_id === taskId;
}

export function getCourseMode(course: Course): LearningMode | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const raw = localStorage.getItem(`opentutor_blocks_${course.id}`);
    if (raw) {
      const layout = JSON.parse(raw) as SpaceLayout;
      if (layout.mode) return layout.mode;
    }
  } catch {
    // Ignore local parse failures and fall back to server metadata.
  }
  const metadata = (course.metadata ?? {}) as Record<string, unknown>;
  const layout = metadata.spaceLayout as SpaceLayout | undefined;
  const mode = layout?.mode ?? metadata.learning_mode;
  return typeof mode === "string" ? (mode as LearningMode) : undefined;
}

export interface ReviewSummary {
  courseId: string;
  courseName: string;
  overdueCount: number;
  urgentCount: number;
  totalCount: number;
}

export type PendingTaskSummary = AgentTask & { courseName: string };

export interface KnowledgeDensitySummary {
  totalConcepts: number;
  sharedConcepts: number;
  densityPct: number;
  topSharedConcepts: string[];
}

export interface ModeRecommendation {
  courseId: string;
  courseName: string;
  currentMode: LearningMode;
  suggestedMode: LearningMode;
  recommendationKey: string;
  reason: string;
  signals: string[];
}

export function modeRecSnoozeStorageKey(courseId: string, recommendationKey: string): string {
  return `opentutor_home_mode_rec_snooze_${courseId}_${recommendationKey}`;
}

export function isModeRecommendationSnoozed(courseId: string, recommendationKey: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    const raw = localStorage.getItem(modeRecSnoozeStorageKey(courseId, recommendationKey));
    if (!raw) return false;
    const ts = Number(raw);
    if (Number.isNaN(ts)) return false;
    return Date.now() - ts < MODE_REC_SNOOZE_MS;
  } catch {
    return false;
  }
}

export function snoozeModeRecommendation(courseId: string, recommendationKey: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(modeRecSnoozeStorageKey(courseId, recommendationKey), String(Date.now()));
  } catch {
    // ignore storage failures
  }
}

export function normalizeConceptLabel(label: string): string {
  return label.trim().toLowerCase().replace(/\s+/g, " ");
}
