"use client";

import { Suspense, lazy } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useT } from "@/lib/i18n-context";

const ProgressView = lazy(() =>
  import("./analytics/progress-view").then((m) => ({ default: m.ProgressView })),
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

function SubViewSkeleton() {
  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="h-4 w-32 bg-muted animate-pulse rounded" />
    </div>
  );
}

/**
 * Analytics section -- unified Progress + Knowledge Graph + Profile.
 *
 * Uses internal sub-tabs for switching between the three analytics views.
 * Each sub-view is lazily loaded to reduce initial bundle size.
 */
export function AnalyticsSection({ courseId }: AnalyticsSectionProps) {
  const t = useT();

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-testid="analytics-section">
      <Tabs defaultValue="progress" className="flex-1 flex flex-col overflow-hidden">
        <div className="px-3 py-1.5 border-b shrink-0">
          <TabsList className="h-7">
            <TabsTrigger value="progress" className="text-xs px-2.5 h-6">
              {t("course.progress")}
            </TabsTrigger>
            <TabsTrigger value="graph" className="text-xs px-2.5 h-6">
              {t("course.graph")}
            </TabsTrigger>
            <TabsTrigger value="profile" className="text-xs px-2.5 h-6">
              {t("course.profile")}
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="progress" className="flex-1 flex flex-col overflow-hidden mt-0">
          <Suspense fallback={<SubViewSkeleton />}>
            <ProgressView courseId={courseId} />
          </Suspense>
        </TabsContent>

        <TabsContent value="graph" className="flex-1 flex flex-col overflow-hidden mt-0">
          <Suspense fallback={<SubViewSkeleton />}>
            <GraphView courseId={courseId} />
          </Suspense>
        </TabsContent>

        <TabsContent value="profile" className="flex-1 flex flex-col overflow-hidden mt-0">
          <Suspense fallback={<SubViewSkeleton />}>
            <ProfileView courseId={courseId} />
          </Suspense>
        </TabsContent>
      </Tabs>
    </div>
  );
}
