"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import Link from "next/link";
import { ArrowLeft, Layout, RefreshCw, Settings } from "lucide-react";
import { NotificationBell } from "./notification-bell";
import { ModeSelector } from "@/components/course/mode-selector";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n-context";
import { syncCourse } from "@/lib/api";
import { useCourseStore } from "@/store/course";
import { useWorkspaceStore } from "@/store/workspace";
import { LAYOUT_PRESETS, PRESET_LABELS, type PresetId } from "@/lib/layout-presets";

interface WorkspaceHeaderProps {
  courseName: string;
  courseId?: string;
}

const PRESET_IDS = Object.keys(LAYOUT_PRESETS) as PresetId[];

export function WorkspaceHeader({
  courseName,
  courseId,
}: WorkspaceHeaderProps) {
  const t = useT();
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [presetOpen, setPresetOpen] = useState(false);
  const presetRef = useRef<HTMLDivElement>(null);
  const fetchContentTree = useCourseStore((s) => s.fetchContentTree);
  const fetchIngestionJobs = useCourseStore((s) => s.fetchIngestionJobs);
  const currentPreset = useWorkspaceStore((s) => s.layout.preset);
  const applyPreset = useWorkspaceStore((s) => s.applyPreset);

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

  // Close dropdown on outside click
  useEffect(() => {
    if (!presetOpen) return;
    const handler = (e: MouseEvent) => {
      if (presetRef.current && !presetRef.current.contains(e.target as Node)) {
        setPresetOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [presetOpen]);

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

        {/* Layout preset switcher */}
        <div className="relative" ref={presetRef}>
          <Button
            variant="ghost"
            size="icon-xs"
            className="text-muted-foreground hover:text-foreground"
            title="Layout preset"
            onClick={() => setPresetOpen((v) => !v)}
          >
            <Layout className="size-3.5" />
          </Button>

          {presetOpen && (
            <div className="absolute right-0 top-full mt-1 z-50 min-w-[180px] rounded-md border border-border bg-popover p-1 shadow-md">
              {PRESET_IDS.map((id) => {
                const meta = PRESET_LABELS[id];
                const active = currentPreset === id;
                return (
                  <button
                    type="button"
                    key={id}
                    onClick={() => {
                      applyPreset(id);
                      setPresetOpen(false);
                    }}
                    className={`flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-xs transition-colors ${
                      active
                        ? "bg-primary/10 text-primary font-medium"
                        : "text-foreground hover:bg-muted"
                    }`}
                  >
                    <span className="flex-1 text-left">{meta.label}</span>
                    <span className="text-[10px] text-muted-foreground">{meta.description}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

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
