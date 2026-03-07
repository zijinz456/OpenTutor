"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import { ArrowLeft, RefreshCw, Search, Settings } from "lucide-react";
import { NotificationBell } from "./notification-bell";
import { ModeSelector } from "@/components/course/mode-selector";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n-context";
import { syncCourse } from "@/lib/api";
import { useCourseStore } from "@/store/course";


interface WorkspaceHeaderProps {
  courseName: string;
  courseId?: string;
}

export function WorkspaceHeader({
  courseName,
  courseId,
}: WorkspaceHeaderProps) {
  const t = useT();
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const fetchContentTree = useCourseStore((s) => s.fetchContentTree);
  const fetchIngestionJobs = useCourseStore((s) => s.fetchIngestionJobs);

  const handleSync = useCallback(async () => {
    if (!courseId || syncing) return;
    setSyncing(true);
    setSyncMessage(null);
    try {
      const result = await syncCourse(courseId);
      const parts: string[] = [];
      if (result.new_files > 0) parts.push(`${result.new_files} new`);
      if (result.updated_files > 0) parts.push(`${result.updated_files} updated`);
      if (result.unchanged_files > 0) parts.push(`${result.unchanged_files} unchanged`);
      setSyncMessage(parts.length > 0 ? parts.join(", ") : "Up to date");

      // Refresh content tree and jobs
      void fetchContentTree(courseId);
      void fetchIngestionJobs(courseId);

      // Clear message after 4 seconds
      setTimeout(() => setSyncMessage(null), 4000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Sync failed";
      setSyncMessage(msg);
      setTimeout(() => setSyncMessage(null), 5000);
    } finally {
      setSyncing(false);
    }
  }, [courseId, syncing, fetchContentTree, fetchIngestionJobs]);

  return (
    <header
      className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3"
      style={{ background: "var(--section-header)" }}
    >
      <div className="flex items-center gap-1.5 min-w-0">
        <Button
          variant="ghost"
          size="icon-xs"
          asChild
          className="shrink-0 text-muted-foreground hover:text-foreground"
          title="Home"
        >
          <Link href="/" aria-label={t("nav.back") || "Back"}>
            <ArrowLeft className="size-3.5" />
          </Link>
        </Button>

        <span className="truncate text-xs font-medium text-foreground">
          {courseName}
        </span>

        {courseId && (
          <Button
            variant="ghost"
            size="icon-xs"
            className="shrink-0 text-muted-foreground hover:text-foreground"
            title={syncing ? "Syncing..." : "Sync course content"}
            onClick={handleSync}
            disabled={syncing}
          >
            <RefreshCw className={`size-3.5 ${syncing ? "animate-spin" : ""}`} />
          </Button>
        )}

        {syncMessage && (
          <span className="text-[10px] text-muted-foreground truncate max-w-[200px]">
            {syncMessage}
          </span>
        )}
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        {/* Learning mode selector */}
        <ModeSelector />

        <Button
          variant="ghost"
          size="icon-xs"
          className="text-muted-foreground hover:text-foreground"
          title="Search (⌘K)"
          onClick={() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }))}
        >
          <Search className="size-3.5" />
        </Button>

        <NotificationBell />

        <Button
          variant="ghost"
          size="icon-xs"
          asChild
          className="text-muted-foreground hover:text-foreground"
          title="Settings"
        >
          <Link href="/settings" aria-label={t("nav.settings") || "Settings"}>
            <Settings className="size-3.5" />
          </Link>
        </Button>
      </div>
    </header>
  );
}
