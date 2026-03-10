"use client";

import { BookOpen, Sparkles, Settings } from "lucide-react";
import type { HealthStatus } from "@/lib/api";

export function DashboardSidebar({
  health,
  t,
  onNavigate,
}: {
  health: HealthStatus | null;
  t: (key: string) => string;
  onNavigate: (path: string) => void;
}) {
  return (
    <aside className="w-full shrink-0 border-b border-border/60 bg-card p-4 md:w-[220px] md:border-b-0 md:border-r md:flex md:flex-col md:gap-6 md:p-5">
      <div className="flex items-center gap-2.5 px-1 py-1">
        <div className="size-8 rounded-xl bg-brand flex items-center justify-center">
          <BookOpen className="size-4 text-brand-foreground" />
        </div>
        <span className="text-base font-bold text-foreground tracking-tight">OpenTutor</span>
      </div>
      <nav className="mt-3 flex flex-wrap gap-1 md:mt-2 md:flex-col">
        <span className="px-3 py-2.5 rounded-xl text-sm font-medium bg-brand-muted text-brand flex items-center gap-2">
          <Sparkles className="size-3.5" />
          {t("nav.dashboard")}
        </span>
        <button
          type="button"
          onClick={() => onNavigate("/settings")}
          className="px-3 py-2.5 rounded-xl text-sm text-muted-foreground hover:bg-muted/60 hover:text-foreground transition-colors text-left flex items-center gap-2"
        >
          <Settings className="size-3.5" />
          {t("nav.settings")}
        </button>
      </nav>
      {health?.deployment_mode === "single_user" && (
        <span className="mt-3 inline-flex w-fit rounded-full bg-muted px-3 py-1.5 text-center text-[11px] font-medium text-muted-foreground md:mt-auto">
          {t("dashboard.singleUser")}
        </span>
      )}
    </aside>
  );
}
