"use client";

import { useWorkspaceStore } from "@/store/workspace";
import { getCourseProgress, getWrongAnswerStats, listProblems } from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { blockRouteHref } from "@/lib/block-system/routes";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import { SummaryCard, useSummaryData } from "../summary-card";

async function loadQuizSummary(courseId: string) {
  const [problems, progress, stats] = await Promise.all([
    listProblems(courseId).catch(() => []),
    getCourseProgress(courseId).catch(() => null),
    getWrongAnswerStats(courseId).catch(() => null),
  ]);
  return { problemCount: problems.length, progress, stats };
}

export default function QuizBlock({ courseId }: BlockComponentProps) {
  const t = useT();
  const refreshKey = useWorkspaceStore((s) => s.sectionRefreshKey.practice);
  const { data, loading } = useSummaryData(courseId, loadQuizSummary, refreshKey);

  const problemCount = data?.problemCount ?? 0;
  const mastery = Math.round((data?.progress?.average_mastery ?? 0) * 100);
  const unmastered = data?.stats?.unmastered ?? 0;

  return (
    <SummaryCard
      href={blockRouteHref("quiz", courseId)!}
      ariaLabel={t("blocks.quiz.label")}
      loading={loading}
      stats={[
        { label: t("blocks.quiz.questions"), value: problemCount },
        { label: t("blocks.quiz.mastery"), value: `${mastery}%`, tone: mastery >= 70 ? "success" : "default" },
        { label: t("blocks.quiz.openMistakes"), value: unmastered, tone: unmastered > 0 ? "warning" : "default" },
      ]}
      emptyText={t("blocks.quiz.empty")}
      ctaLabel={problemCount > 0 ? t("blocks.quiz.start") : undefined}
    />
  );
}
