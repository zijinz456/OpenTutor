"use client";

import { lazy } from "react";
import { TabbedSection, type TabDef } from "./tabbed-section";

const PlanView = lazy(() =>
  import("./plan/plan-view").then((m) => ({ default: m.PlanView })),
);
const ActivityView = lazy(() =>
  import("./plan/activity-view").then((m) => ({ default: m.ActivityView })),
);

interface PlanSectionProps {
  courseId: string;
}

type PlanTab = "plan" | "tasks";

const TABS: TabDef<PlanTab>[] = [
  { id: "plan", label: "Plan", testId: "right-tab-plan" },
  { id: "tasks", label: "Tasks" },
];

export function PlanSection({ courseId }: PlanSectionProps) {
  return (
    <TabbedSection tabs={TABS} defaultTab="plan" testId="plan-section">
      {(activeTab) => (
        <>
          {activeTab === "plan" ? <PlanView courseId={courseId} /> : null}
          {activeTab === "tasks" ? <ActivityView courseId={courseId} /> : null}
        </>
      )}
    </TabbedSection>
  );
}
