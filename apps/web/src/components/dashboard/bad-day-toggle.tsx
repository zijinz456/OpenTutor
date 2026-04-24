"use client";

import { useT } from "@/lib/i18n-context";
import { cn } from "@/lib/utils";
import { useBadDayStore } from "@/store/bad-day";


export function BadDayToggle() {
  const t = useT();
  const active = useBadDayStore((s) => s.isActiveToday());
  const toggle = useBadDayStore((s) => s.toggle);

  return (
    <section
      data-testid="bad-day-toggle"
      className="rounded-2xl border border-border/60 bg-muted/30 p-3"
    >
      <button
        type="button"
        onClick={toggle}
        aria-pressed={active}
        data-testid="bad-day-toggle-button"
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">
            {t("home.badDay.toggle")}
          </p>
          <p className="text-xs text-muted-foreground">Resets at midnight.</p>
        </div>
        <span
          className={cn(
            "relative inline-flex h-6 w-11 shrink-0 rounded-full transition-colors",
            active ? "bg-brand" : "bg-muted",
          )}
        >
          <span
            className={cn(
              "absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform",
              active ? "translate-x-5" : "translate-x-0.5",
            )}
          />
        </span>
      </button>
      {active ? (
        <p
          data-testid="bad-day-toggle-banner"
          className="mt-2 text-xs text-muted-foreground"
        >
          {t("home.badDay.banner")}
        </p>
      ) : null}
    </section>
  );
}
