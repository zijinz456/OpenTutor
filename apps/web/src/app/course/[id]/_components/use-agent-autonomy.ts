"use client";

import { useEffect, type MutableRefObject } from "react";
import { useWorkspaceStore } from "@/store/workspace";
import type { BlockType, LearningMode } from "@/lib/block-system/types";
import type { HealthStatus } from "@/lib/api";
import { BLOCK_REGISTRY } from "@/lib/block-system/registry";
import {
  getUnlockContext,
  isBlockUnlocked,
  updateUnlockContext,
} from "@/lib/block-system/feature-unlock";
import { useT, useTF } from "@/lib/i18n-context";

const REVIEW_CHECK_TTL_MS = 10 * 60 * 1000;
const REVIEW_CHECK_RETRY_MS = 5_000;

interface ReviewCheckLatchState {
  successAt?: number;
  retryAt?: number;
  fingerprint?: string;
}

function readReviewCheckLatch(key: string): ReviewCheckLatchState {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as ReviewCheckLatchState;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeReviewCheckLatch(key: string, value: ReviewCheckLatchState): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // no-op
  }
}

function checkAndSuggestUnlockedBlocks(
  courseId: string,
  totalCourses: number,
  mode: LearningMode | undefined,
  aiActionsEnabled: boolean,
  t: (key: string) => string,
) {
  if (!aiActionsEnabled) return;
  const ctx = { ...getUnlockContext(courseId, totalCourses), mode };
  if ((ctx.sessionCount ?? 0) < 5) return;

  const store = useWorkspaceStore.getState();
  const currentBlocks = store.spaceLayout.blocks;
  const suggestedKey = `opentutor_suggested_unlocks_${courseId}`;

  let alreadySuggested: string[] = [];
  try {
    const raw = localStorage.getItem(suggestedKey);
    if (raw) alreadySuggested = JSON.parse(raw);
  } catch { /* ignore */ }

  const UNLOCK_SUGGESTIONS: Array<{ type: BlockType; message: string }> = [
    { type: "knowledge_graph", message: t("course.unlock.knowledgeGraph") },
    { type: "wrong_answers", message: t("course.unlock.wrongAnswers") },
    { type: "forecast", message: t("course.unlock.forecast") },
    { type: "plan", message: t("course.unlock.plan") },
  ];

  for (const suggestion of UNLOCK_SUGGESTIONS) {
    if (!isBlockUnlocked(suggestion.type, ctx).unlocked) continue;
    if (alreadySuggested.includes(suggestion.type)) continue;
    if (currentBlocks.some((b) => b.type === suggestion.type)) continue;

    const blockLabel = BLOCK_REGISTRY[suggestion.type]?.label ?? suggestion.type.replace(/_/g, " ");

    store.agentAddBlock(
      "agent_insight",
      {
        insightType: "feature_unlock",
        suggestedBlockType: suggestion.type,
        reason: suggestion.message,
      },
      {
        reason: suggestion.message,
        needsApproval: true,
        dismissible: true,
        approvalCta: `${t("course.unlock.add")} ${blockLabel}`,
      },
    );

    alreadySuggested.push(suggestion.type);
    try {
      localStorage.setItem(suggestedKey, JSON.stringify(alreadySuggested));
    } catch { /* ignore */ }

    break;
  }
}

export function useUnlockSuggestions(
  courseId: string,
  courses: unknown[],
  contentTree: unknown[],
  health: HealthStatus | null,
  blocksInitialized: MutableRefObject<boolean>,
) {
  const spaceMode = useWorkspaceStore((s) => s.spaceLayout.mode);
  const t = useT();

  useEffect(() => {
    if (!blocksInitialized.current) return;
    if (courses.length === 0) return;

    if (contentTree.length > 0) {
      updateUnlockContext(courseId, { sourceDocCount: contentTree.length });
    }
    const llmReady = health?.llm_status !== "mock_fallback" && health?.llm_status !== "configuration_required";
    checkAndSuggestUnlockedBlocks(courseId, courses.length, spaceMode, llmReady, t);
  }, [courseId, contentTree.length, courses.length, spaceMode, health?.llm_status, t, blocksInitialized]);
}

export function useReviewCheck(
  courseId: string,
  course: unknown | null,
  aiActionsEnabled: boolean,
) {
  const tf = useTF();

  useEffect(() => {
    if (!course || !aiActionsEnabled) return;
    // Skip review check on fresh installs (no learning history yet)
    const ctx = getUnlockContext(courseId, 1);
    if ((ctx.sessionCount ?? 0) < 3) return;
    const checkKey = `agent_review_check_${courseId}`;
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const runReviewCheck = async (isRetry = false) => {
      const now = Date.now();
      const latch = readReviewCheckLatch(checkKey);
      if (latch.retryAt && now < latch.retryAt) return;

      try {
        const { getReviewSession } = await import("@/lib/api");
        const result = await getReviewSession(courseId);
        if (cancelled) return;

        const urgentItems = result?.items?.filter(
          (item) => item.urgency === "urgent" || item.urgency === "overdue",
        ) ?? [];
        const fingerprint = urgentItems
          .map((item) => `${item.concept_id}:${item.urgency}`)
          .sort()
          .join("|");

        const latestLatch = readReviewCheckLatch(checkKey);
        const shouldSkip =
          latestLatch.successAt != null
          && now - latestLatch.successAt < REVIEW_CHECK_TTL_MS
          && latestLatch.fingerprint === fingerprint;

        if (!shouldSkip && urgentItems.length > 0) {
          const store = useWorkspaceStore.getState();
          const hasInsight = store.spaceLayout.blocks.some(
            (b) => b.type === "agent_insight" && b.config.insightType === "review_needed",
          );
          if (!hasInsight) {
            store.agentAddBlock(
              "agent_insight",
              { insightType: "review_needed" },
              {
                reason: tf("course.reviewNeeded", { count: urgentItems.length }),
                dismissible: true,
              },
            );
          }
        }

        writeReviewCheckLatch(checkKey, {
          successAt: Date.now(),
          fingerprint,
        });
      } catch (e) {
        console.error("[Course] LECTOR review check failed:", e);
        writeReviewCheckLatch(checkKey, { retryAt: Date.now() + REVIEW_CHECK_RETRY_MS });
        if (!cancelled && !isRetry) {
          retryTimer = setTimeout(() => {
            void runReviewCheck(true);
          }, REVIEW_CHECK_RETRY_MS);
        }
      }
    };

    void runReviewCheck();
    return () => {
      cancelled = true;
      if (retryTimer) {
        clearTimeout(retryTimer);
      }
    };
  }, [course, courseId, aiActionsEnabled, tf]);
}
