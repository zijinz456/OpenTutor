"use client";

import { lazy } from "react";
import { TabbedSection, type TabDef } from "./tabbed-section";

const ProgressView = lazy(() =>
  import("./analytics/progress-view").then((m) => ({ default: m.ProgressView })),
);
const ForecastView = lazy(() =>
  import("./analytics/forecast-view").then((m) => ({ default: m.ForecastView })),
);
const GraphView = lazy(() =>
  import("./analytics/graph-view").then((m) => ({ default: m.GraphView })),
);
const ProfileView = lazy(() =>
  import("./analytics/profile-view").then((m) => ({ default: m.ProfileView })),
);
const MisconceptionView = lazy(() =>
  import("./analytics/misconception-view").then((m) => ({ default: m.MisconceptionView })),
);
const ReviewSummaryView = lazy(() =>
  import("./analytics/review-summary-view").then((m) => ({ default: m.ReviewSummaryView })),
);

interface AnalyticsSectionProps {
  courseId: string;
  defaultTab?: AnalyticsTab;
}

type AnalyticsTab = "progress" | "review" | "blindspots" | "forecast" | "graph" | "profile";

const TABS: TabDef<AnalyticsTab>[] = [
  { id: "progress", label: "Stats", testId: "right-tab-progress" },
  { id: "review", label: "Review", testId: "right-tab-review" },
  { id: "blindspots", label: "Blind Spots", testId: "right-tab-blindspots" },
  { id: "forecast", label: "Forecast", testId: "right-tab-forecast" },
  { id: "graph", label: "Graph", testId: "right-tab-graph" },
  { id: "profile", label: "Profile" },
];

export function AnalyticsSection({ courseId, defaultTab = "progress" }: AnalyticsSectionProps) {
  return (
    <TabbedSection
      tabs={TABS}
      defaultTab={TABS.some((tab) => tab.id === defaultTab) ? defaultTab : "progress"}
      testId="analytics-section"
    >
      {(activeTab) => (
        <>
          {activeTab === "progress" ? <ProgressView courseId={courseId} /> : null}
          {activeTab === "review" ? <ReviewSummaryView courseId={courseId} /> : null}
          {activeTab === "blindspots" ? <MisconceptionView courseId={courseId} /> : null}
          {activeTab === "forecast" ? <ForecastView courseId={courseId} /> : null}
          {activeTab === "graph" ? <GraphView courseId={courseId} /> : null}
          {activeTab === "profile" ? <ProfileView courseId={courseId} /> : null}
        </>
      )}
    </TabbedSection>
  );
}
