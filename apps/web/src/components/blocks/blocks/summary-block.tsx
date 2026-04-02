"use client";

import { useCallback, useEffect, useState } from "react";
import { useT } from "@/lib/i18n-context";
import { getCourseProgress, getReviewSession } from "@/lib/api";
import { SkeletonCard } from "@/components/ui/skeleton";
import type { BlockComponentProps } from "@/lib/block-system/registry";

interface DigestItem {
  label: string;
  value: string | number;
  sub?: string;
}

export default function SummaryBlock({ courseId }: BlockComponentProps) {
  const t = useT();
  const [items, setItems] = useState<DigestItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDigest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [progress, reviewSession] = await Promise.all([
        getCourseProgress(courseId),
        getReviewSession(courseId, 5).catch(() => null),
      ]);

      const built: DigestItem[] = [];

      built.push({
        label: t("summary.mastery"),
        value: `${Math.round((progress.average_mastery ?? 0) * 100)}%`,
        sub: progress.completion_percent != null
          ? t("summary.completion").replace("{n}", String(Math.round(progress.completion_percent)))
          : undefined,
      });

      built.push({
        label: t("summary.mastered"),
        value: progress.mastered ?? 0,
        sub: t("summary.masteredOf").replace("{total}", String(progress.total_nodes ?? 0)),
      });

      if (reviewSession != null) {
        built.push({
          label: t("summary.reviewDue"),
          value: reviewSession.count,
          sub: reviewSession.count === 0 ? t("summary.reviewClear") : t("summary.reviewNeeded"),
        });
      }

      if (progress.total_study_minutes != null) {
        const hours = Math.floor(progress.total_study_minutes / 60);
        const mins = progress.total_study_minutes % 60;
        built.push({
          label: t("summary.studyTime"),
          value: hours > 0
            ? t("summary.studyTimeHM").replace("{h}", String(hours)).replace("{m}", String(mins))
            : t("summary.studyTimeM").replace("{m}", String(mins)),
        });
      }

      setItems(built);
    } catch {
      setError(t("summary.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [courseId, t]);

  useEffect(() => {
    void fetchDigest();
  }, [fetchDigest]);

  if (loading) {
    return (
      <div className="p-4">
        <SkeletonCard className="w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-xs text-muted-foreground">{error}</div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="p-4 text-xs text-muted-foreground">{t("summary.empty")}</div>
    );
  }

  return (
    <div role="region" aria-label={t("summary.ariaLabel")} className="p-4 space-y-3">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {t("summary.todayDigest")}
      </p>
      <div className="grid grid-cols-2 gap-2">
        {items.map((item) => (
          <div
            key={item.label}
            className="rounded-xl bg-muted/40 px-3 py-2.5 flex flex-col gap-0.5"
          >
            <span className="text-[10px] text-muted-foreground">{item.label}</span>
            <span className="text-base font-semibold tabular-nums">{item.value}</span>
            {item.sub && (
              <span className="text-[10px] text-muted-foreground leading-tight">{item.sub}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
