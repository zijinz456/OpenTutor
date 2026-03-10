"use client";

import type { Course } from "@/lib/api";
import { getPersona, getOptimalStudyWindows, formatStudyWindow } from "@/lib/learner-persona";
import { Clock } from "lucide-react";
import { getDashboardNowMs, type ReviewSummary } from "./dashboard-utils";
import { DashSection } from "./dash-section";

/** Client-side digest fallback when backend daily_brief is not available. */
export function DigestFallback({
  courses,
  reviewSummaries,
  upcomingDeadlines,
  t,
  tf,
}: {
  courses: Course[];
  reviewSummaries: ReviewSummary[];
  upcomingDeadlines: Array<{ title: string; target_date: string | null }>;
  t: (key: string) => string;
  tf: (key: string, vars?: Record<string, string | number | null | undefined>) => string;
}) {
  const persona = getPersona();
  if (persona.totalSessions === 0) {
    return <p className="text-sm text-muted-foreground">{t("home.todayDigest.empty")}</p>;
  }

  const totalReviewItems = reviewSummaries.reduce((s, r) => s + r.overdueCount + r.urgentCount, 0);
  const nextDeadline = upcomingDeadlines[0];
  const daysUntilDeadline = nextDeadline?.target_date
    ? Math.ceil((new Date(nextDeadline.target_date).getTime() - getDashboardNowMs()) / (1000 * 60 * 60 * 24))
    : null;

  return (
    <div className="space-y-1.5 text-sm text-muted-foreground">
      <p>
        <span className="text-foreground font-medium">{courses.length}</span>{" "}
        {courses.length === 1 ? t("home.digest.activeSpace") : t("home.digest.activeSpaces")} ·{" "}
        {tf("home.digest.sessionsTracked", { count: persona.totalSessions })}
      </p>
      {totalReviewItems > 0 && (
        <p>
          <span className="text-warning font-medium">{totalReviewItems}</span>{" "}
          {t("home.urgentReviews.conceptsFading")}
        </p>
      )}
      {daysUntilDeadline != null && daysUntilDeadline >= 0 && (
        <p>
          {t("home.digest.nextDeadline")} <span className="text-foreground font-medium">{nextDeadline!.title}</span>{" "}
          {tf("home.digest.inDays", { days: daysUntilDeadline })}
        </p>
      )}
    </div>
  );
}

/** Learning rhythm visualization from Learner's Persona data. */
export function LearningRhythm({ t }: { t: (key: string) => string }) {
  const persona = getPersona();
  const windows = getOptimalStudyWindows();

  if (persona.totalSessions < 3) return null;

  const dayLabels = ["S", "M", "T", "W", "T", "F", "S"];
  const timeBlocks = [
    { label: "AM", hours: [6, 7, 8, 9, 10, 11] },
    { label: "PM", hours: [12, 13, 14, 15, 16, 17] },
    { label: "Eve", hours: [18, 19, 20, 21, 22, 23] },
    { label: "Night", hours: [0, 1, 2, 3, 4, 5] },
  ];

  const heatmap: number[][] = Array.from({ length: 7 }, () => [0, 0, 0, 0]);
  let maxCount = 1;
  for (const slot of persona.studyTimes) {
    const blockIdx = timeBlocks.findIndex((b) => b.hours.includes(slot.hour));
    if (blockIdx >= 0 && slot.dayOfWeek >= 0 && slot.dayOfWeek < 7) {
      heatmap[slot.dayOfWeek][blockIdx] += slot.count;
      maxCount = Math.max(maxCount, heatmap[slot.dayOfWeek][blockIdx]);
    }
  }

  return (
    <DashSection title={t("home.studyRhythm")} icon={Clock}>
      <div className="space-y-3">
        <div className="flex gap-1.5">
          <div className="flex flex-col gap-1 pt-5">
            {timeBlocks.map((b) => (
              <span key={b.label} className="text-[10px] text-muted-foreground h-5 flex items-center">{b.label}</span>
            ))}
          </div>
          <div className="flex-1 grid grid-cols-7 gap-1">
            {dayLabels.map((d, i) => (
              <span key={i} className="text-[10px] text-muted-foreground text-center">{d}</span>
            ))}
            {timeBlocks.map((_, blockIdx) =>
              dayLabels.map((_, dayIdx) => {
                const count = heatmap[dayIdx][blockIdx];
                const intensity = count / maxCount;
                const bg = intensity === 0 ? "bg-muted" : intensity < 0.33 ? "bg-brand/20" : intensity < 0.66 ? "bg-brand/45" : "bg-brand/75";
                return (
                  <div key={`${dayIdx}-${blockIdx}`} className={`h-5 rounded-md ${bg} transition-colors`} title={`${dayLabels[dayIdx]} ${timeBlocks[blockIdx].label}: ${count} sessions`} />
                );
              }),
            )}
          </div>
        </div>
        {windows.length > 0 && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-muted-foreground">{t("home.studyRhythm.bestTimes")}</span>
            {windows.map((w, i) => (
              <span key={i} className="text-xs px-2 py-0.5 rounded-full bg-brand-muted text-brand font-medium">{formatStudyWindow(w)}</span>
            ))}
          </div>
        )}
      </div>
    </DashSection>
  );
}
