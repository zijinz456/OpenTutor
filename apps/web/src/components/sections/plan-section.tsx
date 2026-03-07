"use client";

import { lazy } from "react";
import { useWorkspaceStore } from "@/store/workspace";
import type { LearningMode } from "@/lib/block-system/types";
import { TabbedSection, type TabDef } from "./tabbed-section";

const PlanView = lazy(() =>
  import("./plan/plan-view").then((m) => ({ default: m.PlanView })),
);
const CalendarView = lazy(() =>
  import("./plan/calendar-view").then((m) => ({ default: m.CalendarView })),
);
const ActivityView = lazy(() =>
  import("./plan/activity-view").then((m) => ({ default: m.ActivityView })),
);

interface PlanSectionProps {
  courseId: string;
  aiActionsEnabled?: boolean;
  learningMode?: LearningMode;
  defaultTab?: PlanTab;
}

type PlanTab = "plan" | "calendar" | "tasks";

const TABS: TabDef<PlanTab>[] = [
  { id: "plan", label: "Plan", testId: "right-tab-plan" },
  { id: "calendar", label: "Calendar" },
  { id: "tasks", label: "Tasks" },
];

export function PlanSection({
  courseId,
  aiActionsEnabled = true,
  learningMode,
  defaultTab,
}: PlanSectionProps) {
  const storeMode = useWorkspaceStore((s) => s.spaceLayout.mode);
  const mode = learningMode ?? storeMode;
  const resolvedDefaultTab: PlanTab =
    defaultTab ??
    (mode === "course_following"
      ? "calendar"
      : mode === "self_paced"
        ? "tasks"
        : "plan");

  return (
    <TabbedSection tabs={TABS} defaultTab={resolvedDefaultTab} testId="plan-section">
      {(activeTab) => (
        <>
          {activeTab === "plan" ? (
            <PlanView
              courseId={courseId}
              aiActionsEnabled={aiActionsEnabled}
              learningMode={mode}
            />
          ) : null}
          {activeTab === "calendar" ? <CalendarView courseId={courseId} /> : null}
          {activeTab === "tasks" ? <ActivityView courseId={courseId} /> : null}
        </>
      )}
    </TabbedSection>
  );
}
