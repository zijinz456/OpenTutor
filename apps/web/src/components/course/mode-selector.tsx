"use client";

import { useState, useRef, useEffect } from "react";
import { useParams } from "next/navigation";
import { GraduationCap, Compass, Clock, Shield, ChevronDown } from "lucide-react";
import { syncCourseSpaceLayout } from "@/lib/block-system/layout-sync";
import { useWorkspaceStore } from "@/store/workspace";
import { LEARNING_MODE_LIST } from "@/lib/block-system/templates";
import type { LearningMode } from "@/lib/block-system/types";
import { useT } from "@/lib/i18n-context";

const MODE_ICONS: Record<LearningMode, typeof GraduationCap> = {
  course_following: GraduationCap,
  self_paced: Compass,
  exam_prep: Clock,
  maintenance: Shield,
};

const MODE_COLORS: Record<LearningMode, string> = {
  course_following: "text-brand",
  self_paced: "text-info",
  exam_prep: "text-warning",
  maintenance: "text-success",
};

const MODE_BG_COLORS: Record<LearningMode, string> = {
  course_following: "bg-brand-muted",
  self_paced: "bg-info-muted",
  exam_prep: "bg-warning-muted",
  maintenance: "bg-success-muted",
};

interface ModeSelectorProps {
  onModeChange?: (mode: LearningMode) => void;
}

export function ModeSelector({ onModeChange }: ModeSelectorProps) {
  const t = useT();
  const params = useParams();
  const courseId = (params?.id as string) ?? "";
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState<LearningMode | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const currentMode = useWorkspaceStore((s) => s.spaceLayout.mode);
  const setLearningMode = useWorkspaceStore((s) => s.setLearningMode);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setConfirming(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const handleSelect = (mode: LearningMode) => {
    if (mode === currentMode) {
      setOpen(false);
      return;
    }
    if (confirming === mode) {
      setLearningMode(mode);
      if (courseId) {
        void syncCourseSpaceLayout(courseId, useWorkspaceStore.getState().spaceLayout).catch(() => undefined);
      }
      onModeChange?.(mode);
      setOpen(false);
      setConfirming(null);
    } else {
      setConfirming(mode);
    }
  };

  const CurrentIcon = currentMode ? MODE_ICONS[currentMode] : GraduationCap;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => { setOpen((v) => !v); setConfirming(null); }}
        className="flex items-center gap-1 rounded-full px-2.5 py-1 text-xs hover:bg-muted/50 transition-colors"
        title={t("mode.title")}
        aria-label={t("mode.title")}
        aria-expanded={open ? "true" : "false"}
        aria-haspopup="true"
      >
        {currentMode ? (
          <>
            <CurrentIcon className={`size-3.5 ${MODE_COLORS[currentMode]}`} />
            <span className={`hidden sm:inline ${MODE_COLORS[currentMode]} font-medium`}>
              {t(`mode.badge.${currentMode}`)}
            </span>
          </>
        ) : (
          <>
            <GraduationCap className="size-3.5 text-muted-foreground" />
            <span className="hidden sm:inline text-muted-foreground">{t("mode.title")}</span>
          </>
        )}
        <ChevronDown className="size-3 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 w-[280px] rounded-2xl bg-popover p-1.5 card-shadow animate-fade-in">
          <div className="px-2 py-1.5 mb-1">
            <p className="text-xs font-semibold text-foreground">{t("mode.title")}</p>
            <p className="text-[10px] text-muted-foreground">{t("mode.description")}</p>
          </div>
          <div role="tablist" aria-label="Learning modes">
          {LEARNING_MODE_LIST.map((m) => {
            const Icon = MODE_ICONS[m.id];
            const isActive = m.id === currentMode;
            const isConfirming = confirming === m.id;
            return (
              <button
                type="button"
                key={m.id}
                role="tab"
                aria-selected={isActive ? "true" : "false"}
                onClick={() => handleSelect(m.id)}
                className={`flex w-full items-start gap-2.5 rounded-xl px-2 py-2 text-left transition-colors ${
                  isActive
                    ? "bg-muted/30 ring-1 ring-primary/20"
                    : "hover:bg-muted/50"
                }`}
              >
                <div className={`mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-xl ${MODE_BG_COLORS[m.id]}`}>
                  <Icon className={`size-3.5 ${MODE_COLORS[m.id]}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium text-foreground">{t(`mode.${m.id}`)}</span>
                    {isActive && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                        {t("mode.current")}
                      </span>
                    )}
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-0.5 line-clamp-2">
                    {isConfirming ? t("mode.confirmSwitch") : t(`mode.${m.id}.desc`)}
                  </p>
                </div>
              </button>
            );
          })}
          </div>
        </div>
      )}
    </div>
  );
}

/** Compact badge showing current learning mode, for use on course cards. */
export function ModeBadge({ mode }: { mode?: LearningMode }) {
  const t = useT();
  if (!mode) return null;
  const Icon = MODE_ICONS[mode];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${MODE_BG_COLORS[mode]} ${MODE_COLORS[mode]}`}>
      <Icon className="size-3" />
      {t(`mode.badge.${mode}`)}
    </span>
  );
}
