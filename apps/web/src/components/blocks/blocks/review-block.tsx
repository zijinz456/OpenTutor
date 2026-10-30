"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { RotateCcw, ArrowRight } from "lucide-react";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import { getReviewSession, type ReviewItem } from "@/lib/api";
import { useT, useTF } from "@/lib/i18n-context";
import { blockRouteHref } from "@/lib/block-system/routes";

const URGENCY_COLORS: Record<string, string> = {
  overdue: "bg-red-100 text-red-700",
  urgent: "bg-orange-100 text-orange-700",
  warning: "bg-yellow-100 text-yellow-700",
  default: "bg-muted text-muted-foreground",
};

export default function ReviewBlock({ courseId }: BlockComponentProps) {
  const t = useT();
  const tf = useTF();
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getReviewSession(courseId, 5)
      .then((session) => { if (!cancelled) setItems(session.items ?? []); })
      .catch((e) => console.error("[ReviewBlock] fetch failed:", e))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [courseId]);

  if (loading) {
    return (
      <div role="status" aria-live="polite" className="flex items-center justify-center py-8 text-xs text-muted-foreground">
        <RotateCcw className="size-3.5 animate-spin mr-2" />
        {t("block.loading")}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="text-center py-8 text-xs text-muted-foreground">
        {t("blocks.review.empty")}
      </div>
    );
  }

  const topItems = items.slice(0, 3);

  return (
    <div role="list" aria-label={t("blocks.review.label")} className="space-y-2 p-1">
      {topItems.map((item) => (
        <div
          key={item.concept_id}
          role="listitem"
          className="flex items-center gap-3 rounded-xl bg-muted/30 p-3.5"
        >
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-foreground truncate">
              {item.concept_label}
            </p>
            <p className="text-xs text-muted-foreground">
              {t("blocks.review.mastery")} <span className="tabular-nums">{Math.round(item.mastery * 100)}%</span>
            </p>
          </div>
          <span
            className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 ${
              URGENCY_COLORS[item.urgency] ?? URGENCY_COLORS.default
            }`}
          >
            {item.urgency}
          </span>
        </div>
      ))}

      {items.length > 3 && (
        <p className="text-[10px] text-muted-foreground text-center">
          {tf("blocks.review.more", { count: items.length - 3 })}
        </p>
      )}

      <Link
        href={blockRouteHref("review", courseId)!}
        aria-label={t("blocks.review.start")}
        className="flex items-center justify-center gap-1.5 w-full py-2.5 text-sm font-medium text-brand-foreground bg-brand rounded-xl hover:opacity-90 transition-opacity"
      >
        {t("blocks.review.start")}
        <ArrowRight className="size-3.5" />
      </Link>
    </div>
  );
}
