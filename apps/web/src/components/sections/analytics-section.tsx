"use client";

import { lazy } from "react";
import { useT } from "@/lib/i18n-context";
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
const AgentTimeline = lazy(() =>
  import("./agent-timeline").then((m) => ({ default: m.AgentTimeline })),
);

interface AnalyticsSectionProps {
  courseId: string;
  defaultTab?: AnalyticsTab;
}

type AnalyticsTab = "progress" | "review" | "blindspots" | "forecast" | "graph" | "agent" | "profile";

export function AnalyticsSection({ courseId, defaultTab = "progress" }: AnalyticsSectionProps) {
  const t = useT();
  const tabs: TabDef<AnalyticsTab>[] = [
    { id: "progress", label: t("analytics.tab.progress"), testId: "right-tab-progress" },
    { id: "review", label: t("analytics.tab.review"), testId: "right-tab-review" },
    { id: "blindspots", label: t("analytics.tab.blindspots"), testId: "right-tab-blindspots" },
    { id: "forecast", label: t("analytics.tab.forecast"), testId: "right-tab-forecast" },
    { id: "graph", label: t("analytics.tab.graph"), testId: "right-tab-graph" },
    { id: "agent", label: t("analytics.tab.agent"), testId: "right-tab-agent" },
    { id: "profile", label: t("analytics.tab.profile") },
  ];

  return (
    <div role="region" aria-label="Analytics">
    <TabbedSection
      tabs={tabs}
      defaultTab={tabs.some((tab) => tab.id === defaultTab) ? defaultTab : "progress"}
      testId="analytics-section"
    >
      {(activeTab) => (
        <>
          {activeTab === "progress" ? <ProgressView courseId={courseId} /> : null}
          {activeTab === "review" ? <ReviewSummaryView courseId={courseId} /> : null}
          {activeTab === "blindspots" ? <MisconceptionView courseId={courseId} /> : null}
          {activeTab === "forecast" ? <ForecastView courseId={courseId} /> : null}
          {activeTab === "graph" ? <GraphView courseId={courseId} /> : null}
          {activeTab === "agent" ? <AgentTimeline courseId={courseId} /> : null}
          {activeTab === "profile" ? <ProfileView courseId={courseId} /> : null}
        </>
      )}
    </TabbedSection>
    </div>
  );
}
