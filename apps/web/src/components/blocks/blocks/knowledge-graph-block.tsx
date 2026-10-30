"use client";

import { getKnowledgeGraph } from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { blockRouteHref } from "@/lib/block-system/routes";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import { SummaryCard, useSummaryData } from "../summary-card";

export default function KnowledgeGraphBlock({ courseId }: BlockComponentProps) {
  const t = useT();
  const { data, loading } = useSummaryData(courseId, getKnowledgeGraph);

  const nodes = data?.nodes ?? [];
  const edges = data?.edges ?? [];
  const mastered = nodes.filter((n) => n.mastery >= 0.8).length;
  const weakest = [...nodes].sort((a, b) => a.mastery - b.mastery).slice(0, 3);

  return (
    <SummaryCard
      href={blockRouteHref("knowledge_graph", courseId)!}
      ariaLabel={t("blocks.knowledge_graph.label")}
      loading={loading}
      stats={nodes.length > 0 ? [
        { label: t("blocks.knowledge_graph.concepts"), value: nodes.length },
        { label: t("blocks.knowledge_graph.links"), value: edges.length },
        { label: t("blocks.knowledge_graph.mastered"), value: mastered, tone: "success" },
      ] : []}
      items={weakest.map((n) => (
        <span key={n.id} className="flex-1 flex items-center justify-between gap-2 min-w-0">
          <span className="truncate">{n.label}</span>
          <span className="text-muted-foreground tabular-nums shrink-0">{Math.round(n.mastery * 100)}%</span>
        </span>
      ))}
      emptyText={t("blocks.knowledge_graph.empty")}
    />
  );
}
