"use client";

import { useWorkspaceStore } from "@/store/workspace";
import { getCourseProgress, type CourseProgress } from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { blockRouteHref } from "@/lib/block-system/routes";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import { SummaryCard, useSummaryData } from "../summary-card";

export default function ProgressBlock({ courseId }: BlockComponentProps) {
  const t = useT();
  const refreshKey = useWorkspaceStore((s) => s.sectionRefreshKey.analytics);
  const { data, loading } = useSummaryData<CourseProgress>(courseId, getCourseProgress, refreshKey);

  const mastery = Math.round((data?.average_mastery ?? 0) * 100);
  const completion = Math.round(data?.completion_percent ?? 0);

  return (
    <SummaryCard
      href={blockRouteHref("progress", courseId)!}
      ariaLabel={t("blocks.progress.label")}
      loading={loading}
      stats={data ? [
        { label: t("blocks.progress.mastery"), value: `${mastery}%`, tone: "brand" },
        { label: t("blocks.progress.completion"), value: `${completion}%` },
        { label: t("blocks.progress.mastered"), value: `${data.mastered}/${data.total_nodes}`, tone: "success" },
      ] : []}
      emptyText={t("blocks.progress.empty")}
    >
      {data && (
        <div
          role="progressbar"
          aria-label={t("blocks.progress.mastery")}
          aria-valuenow={mastery}
          aria-valuemin={0}
          aria-valuemax={100}
          className="w-full h-1.5 bg-muted/40 rounded-full overflow-hidden"
        >
          <div className="h-full bg-brand rounded-full transition-all duration-500" style={{ width: `${mastery}%` }} />
        </div>
      )}
    </SummaryCard>
  );
}
