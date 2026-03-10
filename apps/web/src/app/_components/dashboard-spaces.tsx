"use client";

import { ArrowRight, BookOpen } from "lucide-react";
import type { Course } from "@/lib/api";
import { ModeBadge } from "@/components/course/mode-selector";
import { DashSection } from "./dash-section";
import {
  CARD_COLORS,
  formatDate,
  getInitials,
  getCourseMode,
} from "./dashboard-utils";

export function CourseSpacesSection({
  courses,
  locale,
  onNavigate,
  t,
}: {
  courses: Course[];
  locale: string;
  onNavigate: (path: string) => void;
  t: (key: string) => string;
}) {
  return (
    <DashSection title={t("home.yourSpaces")} icon={BookOpen}>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {courses.map((course, idx) => {
          const color = CARD_COLORS[idx % CARD_COLORS.length];
          const initials = getInitials(course.name);
          const hasPending = (course.pending_approval_count ?? 0) > 0;
          return (
            <button type="button" key={course.id} onClick={() => onNavigate(`/course/${course.id}`)} className="p-5 rounded-2xl flex flex-col gap-3 text-left card-lift bg-card group">
              <div className="flex items-center gap-3 w-full">
                <div className={`w-10 h-10 ${color.bg} rounded-xl flex items-center justify-center shrink-0`}>
                  <span className={`font-bold text-xs ${color.text}`}>{initials}</span>
                </div>
                <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                  <span className="font-semibold text-sm text-foreground truncate group-hover:text-brand transition-colors">{course.name}</span>
                  <span className="text-[11px] text-muted-foreground">{formatDate(course.updated_at ?? course.created_at)}</span>
                </div>
                <ArrowRight className="size-4 text-muted-foreground/0 group-hover:text-muted-foreground transition-all shrink-0" />
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground line-clamp-1 flex-1">
                  {course.description || `${t("dashboard.scenePrefix")}: ${course.last_scene_id || "study_session"}`}
                </span>
                <ModeBadge mode={getCourseMode(course)} />
              </div>
              {hasPending && (
                <span className="inline-flex w-fit rounded-full px-2.5 py-0.5 text-[11px] font-medium bg-warning-muted text-warning">
                  {locale === "zh"
                    ? `${course.pending_approval_count}${t("dashboard.pendingApprovalsBadge")}`
                    : `${course.pending_approval_count} ${t("dashboard.pendingApprovalsBadge")}`}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </DashSection>
  );
}

export function DashboardEmptyState({
  onNavigate,
  t,
}: {
  onNavigate: (path: string) => void;
  t: (key: string) => string;
}) {
  return (
    <div className="text-center py-24 flex flex-col items-center gap-5 animate-fade-in">
      <div className="size-16 rounded-2xl bg-brand-muted flex items-center justify-center">
        <BookOpen className="size-7 text-brand" />
      </div>
      <h2 className="text-lg font-bold text-foreground">{t("dashboard.empty")}</h2>
      <p className="text-sm text-muted-foreground max-w-sm leading-relaxed">{t("dashboard.emptyDescription")}</p>
      <button type="button" onClick={() => onNavigate("/setup?step=content")} className="h-11 px-7 bg-brand text-brand-foreground rounded-full text-sm font-medium hover:opacity-90 transition-all hover:shadow-md">
        {t("dashboard.create")}
      </button>
    </div>
  );
}
