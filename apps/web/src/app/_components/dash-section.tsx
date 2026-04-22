"use client";

import { useState } from "react";
import type { Sparkles } from "lucide-react";

export function CourseCardsSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="p-5 rounded-2xl flex flex-col gap-3 animate-pulse bg-card card-shadow">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-muted rounded-xl" />
            <div className="flex flex-col gap-1.5 flex-1">
              <div className="h-4 bg-muted rounded-lg w-3/4" />
              <div className="h-3 bg-muted rounded-lg w-1/2" />
            </div>
          </div>
          <div className="h-3 bg-muted rounded-lg w-2/3" />
        </div>
      ))}
    </div>
  );
}

/** Collapsible card section. */
export function DashSection({
  title,
  icon: Icon,
  children,
  badge,
}: {
  title: string;
  icon: typeof Sparkles;
  children: React.ReactNode;
  // Phase 13 T6: string badges allow clamped labels (e.g. "10+") so
  // sections can cap "loud counter" display without lying about totals.
  badge?: number | string;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const badgeHasContent =
    typeof badge === "number" ? badge > 0 : typeof badge === "string" && badge.length > 0;
  return (
    <section className="rounded-2xl bg-card card-shadow overflow-hidden animate-slide-up">
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="w-full flex items-center gap-2.5 px-5 py-3.5 text-left hover:bg-muted/30 transition-colors"
      >
        <div className="size-7 rounded-lg bg-brand-muted flex items-center justify-center shrink-0">
          <Icon className="size-3.5 text-brand" />
        </div>
        <span className="text-sm font-semibold text-foreground flex-1">{title}</span>
        {badgeHasContent && (
          <span className="text-[11px] font-medium bg-brand-muted text-brand px-2.5 py-0.5 rounded-full tabular-nums">
            {badge}
          </span>
        )}
        <span className={`text-muted-foreground transition-transform duration-200 ${collapsed ? "" : "rotate-180"}`}>
          <svg className="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path d="M19 9l-7 7-7-7" />
          </svg>
        </span>
      </button>
      <div
        className={`grid transition-all duration-300 ease-out ${collapsed ? "grid-rows-[0fr]" : "grid-rows-[1fr]"}`}
      >
        <div className="overflow-hidden">
          <div className="px-5 pb-5">{children}</div>
        </div>
      </div>
    </section>
  );
}
