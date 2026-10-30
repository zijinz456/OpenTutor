"use client";

import { RotateCcw, ArrowRight, Sun } from "lucide-react";
import type { Course, AppNotification } from "@/lib/api";
import { DashSection } from "./dash-section";
import { DigestFallback } from "./digest-fallback";
import type { CourseProgressSummary, ReviewSummary } from "./dashboard-utils";

type T = (key: string) => string;
type TF = (key: string, vars?: Record<string, string | number | null | undefined>) => string;

export function TodayDigestSection({
  courses,
  dailyDigest,
  reviewSummaries,
  progressSummaries,
  t,
  tf,
}: {
  courses: Course[];
  dailyDigest: AppNotification | null;
  reviewSummaries: ReviewSummary[];
  progressSummaries: CourseProgressSummary[];
  t: T;
  tf: TF;
}) {
  return (
    <DashSection title={t("home.todayDigest")} icon={Sun}>
      {dailyDigest ? (
        <div className="space-y-2">
          <p className="text-sm font-medium text-foreground">{dailyDigest.title}</p>
          <p className="text-sm text-muted-foreground whitespace-pre-line">{dailyDigest.body}</p>
        </div>
      ) : (
        <DigestFallback
          courses={courses}
          reviewSummaries={reviewSummaries}
          progressSummaries={progressSummaries}
          t={t}
          tf={tf}
        />
      )}
    </DashSection>
  );
}

export function UrgentReviewsSection({
  reviewSummaries,
  totalUrgentReviews,
  onNavigate,
  t,
  tf,
}: {
  reviewSummaries: ReviewSummary[];
  totalUrgentReviews: number;
  onNavigate: (path: string) => void;
  t: T;
  tf: TF;
}) {
  return (
    <DashSection title={t("home.urgentReviews")} icon={RotateCcw} badge={totalUrgentReviews}>
      {reviewSummaries.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("home.urgentReviews.empty")}</p>
      ) : (
        <div className="space-y-2">
          {reviewSummaries.map((rs) => (
            <button key={rs.courseId} type="button" onClick={() => onNavigate(`/course/${rs.courseId}/review`)} className="w-full flex items-center gap-3 rounded-xl bg-muted/30 p-3.5 text-left hover:bg-muted/50 transition-colors">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-foreground truncate">{rs.courseName}</p>
                <p className="text-xs text-muted-foreground">
                  {rs.overdueCount > 0 && <span className="text-destructive font-medium">{tf("home.reviews.overdue", { count: rs.overdueCount })}</span>}
                  {rs.overdueCount > 0 && rs.urgentCount > 0 && " · "}
                  {rs.urgentCount > 0 && <span className="text-warning font-medium">{tf("home.reviews.urgent", { count: rs.urgentCount })}</span>}
                  {" · "}{tf("home.reviews.total", { count: rs.totalCount })}
                </p>
              </div>
              <ArrowRight className="size-4 text-muted-foreground shrink-0" />
            </button>
          ))}
        </div>
      )}
    </DashSection>
  );
}
