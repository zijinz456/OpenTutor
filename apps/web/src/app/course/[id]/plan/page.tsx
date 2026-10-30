"use client";

import { useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { useWorkspaceStore } from "@/store/workspace";
import { PlanSection } from "@/components/sections/plan-section";
import { useT } from "@/lib/i18n-context";
import { isLearningMode } from "@/lib/block-system/layout-storage";
import type { LearningMode } from "@/lib/block-system/types";
import { CoursePageFrame } from "../_components/course-page-frame";
import { useCourseContext } from "../_hooks/course-context";

const PLAN_TABS = ["plan", "calendar", "tasks", "timeline"] as const;
type PlanTab = (typeof PLAN_TABS)[number];

export default function PlanPage() {
  const t = useT();
  const searchParams = useSearchParams();
  const { courseId, course, aiActionsEnabled } = useCourseContext();
  const spaceMode = useWorkspaceStore((s) => s.spaceLayout.mode);

  const resolvedMode = useMemo<LearningMode | undefined>(() => {
    const metadata = (course?.metadata as Record<string, unknown> | undefined) ?? {};
    const layout = metadata.spaceLayout;
    const layoutMode = layout && typeof layout === "object"
      ? (layout as Record<string, unknown>).mode
      : undefined;
    const metaMode = metadata.learning_mode;
    return spaceMode
      ?? (isLearningMode(layoutMode) ? layoutMode : undefined)
      ?? (isLearningMode(metaMode) ? metaMode : undefined);
  }, [course?.metadata, spaceMode]);

  const requestedTab = searchParams.get("tab");
  const defaultTab: PlanTab = PLAN_TABS.includes(requestedTab as PlanTab)
    ? (requestedTab as PlanTab)
    : "plan";

  return (
    <CoursePageFrame title={t("course.plan")}>
      <PlanSection
        courseId={courseId}
        aiActionsEnabled={aiActionsEnabled}
        learningMode={resolvedMode}
        defaultTab={defaultTab}
      />
    </CoursePageFrame>
  );
}
