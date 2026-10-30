"use client";

import { useSearchParams } from "next/navigation";
import { AnalyticsSection, type AnalyticsTab } from "@/components/sections/analytics-section";
import { ModeSelector } from "@/components/course/mode-selector";
import { useT } from "@/lib/i18n-context";
import { CoursePageFrame } from "../_components/course-page-frame";
import { useCourseContext } from "../_hooks/course-context";

const PROFILE_TABS: AnalyticsTab[] = [
  "progress", "review", "blindspots", "forecast", "graph", "agent", "profile",
];

export default function ProfilePage() {
  const t = useT();
  const searchParams = useSearchParams();
  const { courseId } = useCourseContext();

  const requestedTab = searchParams.get("tab");
  const tab: AnalyticsTab = PROFILE_TABS.includes(requestedTab as AnalyticsTab)
    ? (requestedTab as AnalyticsTab)
    : "profile";

  return (
    <CoursePageFrame title={t("course.profile")} mainClassName="space-y-6">
      {/* Mode selection section */}
      <section className="rounded-2xl bg-card card-shadow p-5">
        <h2 className="text-sm font-semibold text-foreground mb-1">{t("mode.title")}</h2>
        <p className="text-xs text-muted-foreground mb-3">{t("mode.description")}</p>
        <ModeSelector />
      </section>

      {/* Full analytics view with mode-aware default tab */}
      <div className="rounded-2xl bg-card card-shadow overflow-hidden min-h-[380px]">
        <AnalyticsSection courseId={courseId} defaultTab={tab} />
      </div>
    </CoursePageFrame>
  );
}
