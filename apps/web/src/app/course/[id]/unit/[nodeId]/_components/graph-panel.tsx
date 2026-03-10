import { Suspense, lazy } from "react";

const GraphView = lazy(() =>
  import("@/components/sections/analytics/graph-view").then((m) => ({ default: m.GraphView })),
);

type TranslateFn = (key: string) => string;

interface GraphPanelProps {
  courseId: string;
  focusTerms: string[];
  t: TranslateFn;
}

export function GraphPanel({ courseId, focusTerms, t }: GraphPanelProps) {
  return (
    <section className="rounded-2xl bg-card card-shadow overflow-hidden h-[360px]">
      <div className="px-5 py-3 border-b border-border/60 bg-muted/20">
        <h2 className="text-base font-semibold">{t("course.graph")}</h2>
        <p className="text-xs text-muted-foreground mt-0.5">{t("unit.graph.desc")}</p>
      </div>
      <Suspense fallback={<div className="p-4 text-sm text-muted-foreground animate-pulse">{t("unit.loading.graph")}</div>}>
        <GraphView courseId={courseId} focusTerms={focusTerms} maxNodes={24} />
      </Suspense>
    </section>
  );
}
