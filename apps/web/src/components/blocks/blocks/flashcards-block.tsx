"use client";

import { useWorkspaceStore } from "@/store/workspace";
import { getDueFlashcards, type DueFlashcardsResult } from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { blockRouteHref } from "@/lib/block-system/routes";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import { SummaryCard, useSummaryData } from "../summary-card";

export default function FlashcardsBlock({ courseId }: BlockComponentProps) {
  const t = useT();
  const refreshKey = useWorkspaceStore((s) => s.sectionRefreshKey.practice);
  const { data, loading } = useSummaryData<DueFlashcardsResult>(courseId, getDueFlashcards, refreshKey);

  const due = data?.due_count ?? 0;
  const batches = data?.total_batches ?? 0;
  const preview = (data?.cards ?? []).slice(0, 2);

  return (
    <SummaryCard
      href={blockRouteHref("flashcards", courseId)!}
      ariaLabel={t("blocks.flashcards.label")}
      loading={loading}
      stats={[
        { label: t("blocks.flashcards.due"), value: due, tone: due > 0 ? "warning" : "success" },
        { label: t("blocks.flashcards.decks"), value: batches },
      ]}
      items={preview.map((card) => <span key={card.id} className="truncate">{card.front}</span>)}
      emptyText={t("blocks.flashcards.empty")}
      ctaLabel={due > 0 ? t("blocks.flashcards.study") : undefined}
    />
  );
}
