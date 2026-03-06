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

interface AnalyticsSectionProps {
  courseId: string;
}

type AnalyticsTab = "progress" | "forecast" | "graph" | "profile";

const TABS: TabDef<AnalyticsTab>[] = [
  { id: "progress", label: "Stats", testId: "right-tab-progress" },
  { id: "forecast", label: "Forecast", testId: "right-tab-forecast" },
  { id: "graph", label: "Graph", testId: "right-tab-graph" },
  { id: "profile", label: "Profile" },
];

export function AnalyticsSection({ courseId }: AnalyticsSectionProps) {
  return (
    <TabbedSection tabs={TABS} defaultTab="progress" testId="analytics-section">
      {(activeTab) => (
        <>
          {activeTab === "progress" ? <ProgressView courseId={courseId} /> : null}
          {activeTab === "forecast" ? <ForecastView courseId={courseId} /> : null}
          {activeTab === "graph" ? <GraphView courseId={courseId} /> : null}
          {activeTab === "profile" ? <ProfileView courseId={courseId} /> : null}
        </>
      )}
    </TabbedSection>
  );
}
