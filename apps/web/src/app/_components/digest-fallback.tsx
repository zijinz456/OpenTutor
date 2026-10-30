"use client";

import type { Course } from "@/lib/api";
import type { CourseProgressSummary, ReviewSummary } from "./dashboard-utils";

/** Client-side digest fallback when the backend daily_brief is not available. */
export function DigestFallback({
  courses,
  reviewSummaries,
  progressSummaries,
  t,
  tf,
}: {
  courses: Course[];
  reviewSummaries: ReviewSummary[];
  progressSummaries: CourseProgressSummary[];
  t: (key: string) => string;
  tf: (key: string, vars?: Record<string, string | number | null | undefined>) => string;
}) {
  const totalReviewItems = reviewSummaries.reduce((s, r) => s + r.overdueCount + r.urgentCount, 0);
  const averageMastery = progressSummaries.length > 0
    ? Math.round(
      (progressSummaries.reduce((s, p) => s + p.averageMastery, 0) / progressSummaries.length) * 100,
    )
    : null;

  if (courses.length === 0 || (totalReviewItems === 0 && averageMastery == null)) {
    return <p className="text-sm text-muted-foreground">{t("home.todayDigest.empty")}</p>;
  }

  return (
    <div className="space-y-1.5 text-sm text-muted-foreground">
      <p>
        <span className="text-foreground font-medium">{courses.length}</span>{" "}
        {courses.length === 1 ? t("home.digest.activeSpace") : t("home.digest.activeSpaces")}
        {averageMastery != null && (
          <>
            {" · "}
            {tf("home.digest.averageMastery", { value: averageMastery })}
          </>
        )}
      </p>
      {totalReviewItems > 0 && (
        <p>
          <span className="text-warning font-medium">{totalReviewItems}</span>{" "}
          {t("home.urgentReviews.conceptsFading")}
        </p>
      )}
    </div>
  );
}
