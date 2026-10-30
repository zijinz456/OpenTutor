"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useT } from "@/lib/i18n-context";
import { SkeletonCard } from "@/components/ui/skeleton";

export interface SummaryStat {
  label: string;
  value: string | number;
  tone?: "default" | "success" | "warning" | "destructive" | "brand";
}

const TONE_CLASS: Record<NonNullable<SummaryStat["tone"]>, string> = {
  default: "text-foreground",
  success: "text-success",
  warning: "text-warning",
  destructive: "text-destructive",
  brand: "text-brand",
};

interface SummaryCardProps {
  /** Route the "Open" link points to. */
  href: string;
  /** Accessible label for the card region. */
  ariaLabel: string;
  loading?: boolean;
  /** 1-3 key numbers. */
  stats?: SummaryStat[];
  /** Optional list of latest items. */
  items?: ReactNode[];
  /** Shown when there are no stats and no items. */
  emptyText?: string;
  /** Override the CTA label (defaults to "Open"). */
  ctaLabel?: string;
  children?: ReactNode;
}

/**
 * Compact summary card used by workspace blocks. The dedicated route is the
 * canonical UI; the card only shows a few numbers and links to it.
 */
export function SummaryCard({
  href,
  ariaLabel,
  loading = false,
  stats = [],
  items = [],
  emptyText,
  ctaLabel,
  children,
}: SummaryCardProps) {
  const t = useT();

  if (loading) {
    return (
      <div className="p-4" role="status" aria-live="polite">
        <SkeletonCard className="w-full" />
      </div>
    );
  }

  const isEmpty = stats.length === 0 && items.length === 0 && !children;

  return (
    <div role="region" aria-label={ariaLabel} className="p-4 space-y-3">
      {stats.length > 0 && (
        <div className={`grid gap-2 ${stats.length === 1 ? "grid-cols-1" : stats.length === 2 ? "grid-cols-2" : "grid-cols-3"}`}>
          {stats.map((stat) => (
            <div key={stat.label} className="rounded-xl bg-muted/40 px-3 py-2.5 flex flex-col gap-0.5">
              <span className="text-[10px] text-muted-foreground">{stat.label}</span>
              <span className={`text-base font-semibold tabular-nums ${TONE_CLASS[stat.tone ?? "default"]}`}>
                {stat.value}
              </span>
            </div>
          ))}
        </div>
      )}

      {items.length > 0 && (
        <ul className="space-y-1.5">
          {items.map((item, i) => (
            <li key={i} className="flex items-center gap-2 rounded-xl bg-muted/30 px-3 py-2 text-xs text-foreground">
              {item}
            </li>
          ))}
        </ul>
      )}

      {children}

      {isEmpty && emptyText && (
        <p className="text-xs text-muted-foreground text-center py-2">{emptyText}</p>
      )}

      <Link
        href={href}
        className="flex items-center justify-center gap-1.5 w-full py-2 text-sm font-medium text-brand bg-brand-muted/50 rounded-xl hover:bg-brand-muted transition-colors"
      >
        {ctaLabel ?? t("block.open")}
        <ArrowRight className="size-3.5" aria-hidden="true" />
      </Link>
    </div>
  );
}

/** Fetch once per course for a summary card; errors resolve to `null`. */
export function useSummaryData<T>(
  courseId: string,
  loader: (courseId: string) => Promise<T>,
  refreshKey = 0,
): { data: T | null; loading: boolean } {
  const [state, setState] = useState<{ data: T | null; loading: boolean }>({ data: null, loading: true });

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true }));
    loader(courseId)
      .then((data) => { if (!cancelled) setState({ data, loading: false }); })
      .catch((e) => {
        console.error("[SummaryCard] fetch failed:", e);
        if (!cancelled) setState({ data: null, loading: false });
      });
    return () => { cancelled = true; };
    // `loader` is expected to be a stable module-level function.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, refreshKey]);

  return state;
}
