import { useEffect, useMemo, useState, useCallback } from "react";
import { useChatStore } from "@/store/chat";
import { useWorkspaceStore } from "@/store/workspace";
import {
  listWrongAnswers,
  getReviewSession,
  type ChatAction,
  type WrongAnswer,
  type ReviewItem,
} from "@/lib/api";
import { buildFocusTerms, findNodeById, findPathToNode } from "@/lib/content-tree";
import { useCourseContext } from "../../../_hooks/course-context";
import {
  matchesFocus,
  scoreWrongAnswerFocus,
  buildErrorPatternSummary,
  buildMasterySummary,
  buildErrorTrendSummary,
  recommendQuizDifficulty,
  modeHintFromDifficulty,
} from "./unit-utils";

export function useUnitData(courseId: string, nodeId: string) {
  // Course bootstrap (courses, active course, content tree, health) is owned
  // by app/course/[id]/layout.tsx.
  const { course, contentTree, aiActionsEnabled } = useCourseContext();
  const setSelectedNodeId = useWorkspaceStore((s) => s.setSelectedNodeId);
  const [wrongAnswers, setWrongAnswers] = useState<WrongAnswer[]>([]);
  const [trendBaseAnswers, setTrendBaseAnswers] = useState<WrongAnswer[]>([]);
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [loadedSignalsKey, setLoadedSignalsKey] = useState<string | null>(null);

  useEffect(() => {
    setSelectedNodeId(nodeId);
  }, [nodeId, setSelectedNodeId]);

  const node = useMemo(() => findNodeById(contentTree, nodeId), [contentTree, nodeId]);
  const nodePath = useMemo(() => findPathToNode(contentTree, nodeId), [contentTree, nodeId]);
  const parentNode = nodePath.length > 1 ? nodePath[nodePath.length - 2] : null;
  const signalsKey = `${courseId}:${nodeId}`;
  const siblingNodes = useMemo(
    () => (parentNode?.children ?? []).filter((child) => child.id !== nodeId),
    [parentNode, nodeId],
  );
  const focusTerms = useMemo(() => (node ? buildFocusTerms(node) : []), [node]);

  useEffect(() => {
    if (!node) return;

    listWrongAnswers(courseId)
      .then((items) => {
        if (!items) {
          setWrongAnswers([]);
          return;
        }
        const scored = items
          .map((item) => ({ item, score: scoreWrongAnswerFocus(item, focusTerms) }))
          .sort((a, b) => b.score - a.score);
        const matched = scored.filter((entry) => entry.score > 0).map((entry) => entry.item);
        const focused = matched.length > 0 ? matched : items;
        setTrendBaseAnswers(focused);
        setWrongAnswers(focused.slice(0, 12));
      })
      .catch((e) => {
        console.error("[Unit] wrong answers fetch failed:", e);
        setWrongAnswers([]);
        setTrendBaseAnswers([]);
      });

    getReviewSession(courseId, 30)
      .then((session) => {
        const allItems = session?.items ?? [];
        const filtered = allItems.filter((item) => matchesFocus(item.concept_label, focusTerms));
        setReviewItems((filtered.length > 0 ? filtered : allItems).slice(0, 12));
      })
      .catch((e) => {
        console.error("[Unit] review session fetch failed:", e);
        setReviewItems([]);
      })
      .finally(() => setLoadedSignalsKey(signalsKey));
  }, [courseId, focusTerms, node, signalsKey]);

  const loadingSignals = Boolean(node) && loadedSignalsKey !== signalsKey;

  const handleAction = useCallback((action: ChatAction) => {
    if (action.action === "data_updated") {
      const section = action.value as string;
      if (section) {
        useWorkspaceStore
          .getState()
          .triggerRefresh(section as "notes" | "practice" | "analytics" | "plan");
      }
    }
  }, []);

  useEffect(() => {
    const unregister = useChatStore.getState().registerOnAction(handleAction);
    return unregister;
  }, [handleAction]);

  const errorPatterns = useMemo(() => buildErrorPatternSummary(wrongAnswers), [wrongAnswers]);
  const masterySummary = useMemo(() => buildMasterySummary(reviewItems), [reviewItems]);
  const errorTrend = useMemo(() => buildErrorTrendSummary(trendBaseAnswers), [trendBaseAnswers]);
  const difficultyRec = useMemo(
    () => recommendQuizDifficulty(masterySummary, errorTrend, trendBaseAnswers.length),
    [masterySummary, errorTrend, trendBaseAnswers.length],
  );
  const quizModeHint = useMemo(() => modeHintFromDifficulty(difficultyRec.level), [difficultyRec.level]);
  const urgentReviews = reviewItems.filter(
    (item) => item.urgency === "urgent" || item.urgency === "overdue",
  ).length;

  return {
    course,
    node,
    nodePath,
    parentNode,
    siblingNodes,
    focusTerms,
    wrongAnswers,
    reviewItems,
    loadingSignals,
    aiActionsEnabled,
    errorPatterns,
    masterySummary,
    errorTrend,
    difficultyRec,
    quizModeHint,
    urgentReviews,
  };
}
