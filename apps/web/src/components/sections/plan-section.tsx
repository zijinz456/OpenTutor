"use client";

import { Suspense, lazy } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useT } from "@/lib/i18n-context";

const PlanView = lazy(() =>
  import("./plan/plan-view").then((m) => ({ default: m.PlanView })),
);
const ActivityView = lazy(() =>
  import("./plan/activity-view").then((m) => ({ default: m.ActivityView })),
);

interface PlanSectionProps {
  courseId: string;
}

function SubViewSkeleton() {
  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="h-4 w-32 bg-muted animate-pulse rounded" />
    </div>
  );
}

/**
 * Plan section -- unified Study Plan + Tasks.
 *
 * Uses internal sub-tabs for switching between plan and activity views.
 * Each sub-view is lazily loaded to reduce initial bundle size.
 */
export function PlanSection({ courseId }: PlanSectionProps) {
  const t = useT();

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-testid="plan-section">
      <Tabs defaultValue="plan" className="flex-1 flex flex-col overflow-hidden">
        <div className="px-3 py-1.5 border-b shrink-0">
          <TabsList className="h-7">
            <TabsTrigger value="plan" className="text-xs px-2.5 h-6">
              {t("course.plan")}
            </TabsTrigger>
            <TabsTrigger value="tasks" className="text-xs px-2.5 h-6">
              {t("course.activity")}
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="plan" className="flex-1 flex flex-col overflow-hidden mt-0">
          <Suspense fallback={<SubViewSkeleton />}>
            <PlanView courseId={courseId} />
          </Suspense>
        </TabsContent>

        <TabsContent value="tasks" className="flex-1 flex flex-col overflow-hidden mt-0">
          <Suspense fallback={<SubViewSkeleton />}>
            <ActivityView courseId={courseId} />
          </Suspense>
        </TabsContent>
      </Tabs>
    </div>
  );
}
