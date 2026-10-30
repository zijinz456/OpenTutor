"use client";

import { useWorkspaceStore } from "@/store/workspace";
import { getWrongAnswerStats, listWrongAnswers } from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { blockRouteHref } from "@/lib/block-system/routes";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import { SummaryCard, useSummaryData } from "../summary-card";

async function loadMistakes(courseId: string) {
  const [stats, items] = await Promise.all([
    getWrongAnswerStats(courseId).catch(() => null),
    listWrongAnswers(courseId).catch(() => []),
  ]);
  return { stats, latest: (items ?? []).slice(0, 3) };
}

export default function WrongAnswersBlock({ courseId }: BlockComponentProps) {
  const t = useT();
  const refreshKey = useWorkspaceStore((s) => s.sectionRefreshKey.practice);
  const { data, loading } = useSummaryData(courseId, loadMistakes, refreshKey);

  const total = data?.stats?.total ?? 0;
  const unmastered = data?.stats?.unmastered ?? 0;
  const mastered = data?.stats?.mastered ?? 0;

  return (
    <SummaryCard
      href={blockRouteHref("wrong_answers", courseId)!}
      ariaLabel={t("blocks.wrong_answers.label")}
      loading={loading}
      stats={total > 0 ? [
        { label: t("blocks.wrong_answers.open"), value: unmastered, tone: unmastered > 0 ? "destructive" : "success" },
        { label: t("blocks.wrong_answers.mastered"), value: mastered, tone: "success" },
      ] : []}
      items={(data?.latest ?? []).map((item) => (
        <span key={item.id} className="truncate">{item.question ?? item.id}</span>
      ))}
      emptyText={t("blocks.wrong_answers.empty")}
    />
  );
}
