"use client";

import { useCourseStore } from "@/store/course";
import { useWorkspaceStore } from "@/store/workspace";
import { listGeneratedNoteBatches, type GeneratedAssetBatchSummary } from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { blockRouteHref } from "@/lib/block-system/routes";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import { SummaryCard, useSummaryData } from "../summary-card";

export default function NotesBlock({ courseId }: BlockComponentProps) {
  const t = useT();
  const contentTree = useCourseStore((s) => s.contentTree);
  const refreshKey = useWorkspaceStore((s) => s.sectionRefreshKey.notes);
  const { data, loading } = useSummaryData<GeneratedAssetBatchSummary[]>(courseId, listGeneratedNoteBatches, refreshKey);

  const batches = data ?? [];
  const latest = batches.slice(0, 3);

  return (
    <SummaryCard
      href={blockRouteHref("notes", courseId)!}
      ariaLabel={t("blocks.notes.label")}
      loading={loading}
      stats={[
        { label: t("blocks.notes.sections"), value: contentTree.length },
        { label: t("blocks.notes.generated"), value: batches.length, tone: "brand" },
      ]}
      items={latest.map((b) => <span key={b.batch_id} className="truncate">{b.title}</span>)}
      emptyText={t("blocks.notes.empty")}
    />
  );
}
