"use client";

import { lazy } from "react";
import { useWorkspaceStore } from "@/store/workspace";
import type { LearningMode } from "@/lib/block-system/types";
import { useT } from "@/lib/i18n-context";
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
const TimelineView = lazy(() =>
  import("./plan/timeline-view").then((m) => ({ default: m.TimelineView })),
);

interface PlanSectionProps {
  courseId: string;
  aiActionsEnabled?: boolean;
  learningMode?: LearningMode;
  defaultTab?: PlanTab;
}

type PlanTab = "plan" | "calendar" | "tasks" | "timeline";

export function PlanSection({
  courseId,
  aiActionsEnabled = true,
  learningMode,
  defaultTab,
}: PlanSectionProps) {
  const t = useT();
  const storeMode = useWorkspaceStore((s) => s.spaceLayout.mode);
  const mode = learningMode ?? storeMode;
  const tabs: TabDef<PlanTab>[] = [
    { id: "plan", label: t("plan.tabs.plan"), testId: "right-tab-plan" },
    { id: "calendar", label: t("plan.tabs.calendar") },
    { id: "timeline", label: "时间线" },
    { id: "tasks", label: t("plan.tabs.tasks") },
  ];
  const resolvedDefaultTab: PlanTab =
    defaultTab ??
    (mode === "course_following"
      ? "calendar"
      : mode === "self_paced"
        ? "tasks"
        : "plan");

  return (
    <TabbedSection tabs={tabs} defaultTab={resolvedDefaultTab} testId="plan-section">
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
          {activeTab === "timeline" ? <TimelineView courseId={courseId} /> : null}
          {activeTab === "tasks" ? <ActivityView courseId={courseId} /> : null}
        </>
      )}
    </TabbedSection>
  );
}
