"use client";

import { useWorkspaceStore } from "@/store/workspace";
import { getNextAction, listStudyGoals } from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { blockRouteHref } from "@/lib/block-system/routes";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import { SummaryCard, useSummaryData } from "../summary-card";

async function loadPlanSummary(courseId: string) {
  const [goals, nextAction] = await Promise.all([
    listStudyGoals(courseId, "active").catch(() => []),
    getNextAction(courseId).catch(() => null),
  ]);
  return { goals, nextAction };
}

function daysUntil(iso: string): number {
  return Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
}

export default function PlanBlock({ courseId }: BlockComponentProps) {
  const t = useT();
  const refreshKey = useWorkspaceStore((s) => s.sectionRefreshKey.plan);
  const { data, loading } = useSummaryData(courseId, loadPlanSummary, refreshKey);

  const goals = data?.goals ?? [];
  const deadlines = goals
    .filter((g) => g.target_date)
    .sort((a, b) => new Date(a.target_date!).getTime() - new Date(b.target_date!).getTime());
  const nextDeadline = deadlines[0];
  const nextDays = nextDeadline ? daysUntil(nextDeadline.target_date!) : null;

  return (
    <SummaryCard
      href={blockRouteHref("plan", courseId)!}
      ariaLabel={t("blocks.plan.label")}
      loading={loading}
      stats={[
        { label: t("blocks.plan.activeGoals"), value: goals.length },
        {
          label: t("blocks.plan.nextDeadline"),
          value: nextDays == null ? "—" : t("blocks.plan.daysLeft").replace("{n}", String(nextDays)),
          tone: nextDays != null && nextDays <= 3 ? "warning" : "default",
        },
      ]}
      items={data?.nextAction ? [
        <span key="next" className="flex-1 min-w-0">
          <span className="text-muted-foreground">{t("blocks.plan.nextAction")}: </span>
          <span className="font-medium">{data.nextAction.title}</span>
        </span>,
      ] : []}
      emptyText={t("blocks.plan.empty")}
    />
  );
}
