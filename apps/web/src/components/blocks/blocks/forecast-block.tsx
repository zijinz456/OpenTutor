"use client";

import { getForgettingForecast, type ForgettingForecast } from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { blockRouteHref } from "@/lib/block-system/routes";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import { SummaryCard, useSummaryData } from "../summary-card";

/**
 * Compact forecast card. The full forecast UI lives in
 * `components/sections/analytics/forecast-view.tsx` (profile?tab=forecast).
 */
export default function ForecastBlock({ courseId }: BlockComponentProps) {
  const t = useT();
  const { data, loading } = useSummaryData<ForgettingForecast>(courseId, getForgettingForecast);

  const total = data?.total_items ?? 0;
  const urgent = data?.urgent_count ?? 0;
  const warning = data?.warning_count ?? 0;
  const onTrack = Math.max(0, total - urgent - warning);
  const health = total > 0 ? Math.round((onTrack / total) * 100) : 0;
  const atRisk = (data?.predictions ?? [])
    .filter((p) => p.urgency !== "ok")
    .slice(0, 3);

  return (
    <SummaryCard
      href={blockRouteHref("forecast", courseId)!}
      ariaLabel={t("blocks.forecast.label")}
      loading={loading}
      stats={total > 0 ? [
        {
          label: t("blocks.forecast.retention"),
          value: `${health}%`,
          tone: health >= 80 ? "success" : health >= 50 ? "warning" : "destructive",
        },
        { label: t("blocks.forecast.urgent"), value: urgent, tone: urgent > 0 ? "destructive" : "default" },
        { label: t("blocks.forecast.onTrack"), value: onTrack, tone: "success" },
      ] : []}
      items={atRisk.map((p, i) => (
        <span key={p.content_node_id ?? i} className="flex-1 flex items-center justify-between gap-2 min-w-0">
          <span className="truncate">{p.title}</span>
          <span className="text-muted-foreground tabular-nums shrink-0">{Math.round(p.current_retrievability * 100)}%</span>
        </span>
      ))}
      emptyText={t("blocks.forecast.empty")}
    />
  );
}
