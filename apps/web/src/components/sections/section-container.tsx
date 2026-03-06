"use client";

import { Suspense, lazy } from "react";
import { useWorkspaceStore, type SectionId } from "@/store/workspace";
import { SECTIONS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { PdfViewerOverlay } from "./pdf-viewer";

const NotesSection = lazy(() =>
  import("./notes-section").then((m) => ({ default: m.NotesSection })),
);
const PracticeSection = lazy(() =>
  import("./practice-section").then((m) => ({ default: m.PracticeSection })),
);
const AnalyticsSection = lazy(() =>
  import("./analytics-section").then((m) => ({ default: m.AnalyticsSection })),
);
const PlanSection = lazy(() =>
  import("./plan-section").then((m) => ({ default: m.PlanSection })),
);

interface SectionContainerProps {
  courseId: string;
  reviewEnabled: boolean;
  aiActionsEnabled?: boolean;
  visibleSections?: SectionId[];
}

function SectionSkeleton() {
  return (
    <div className="flex-1 flex flex-col gap-3 p-4">
      <div className="h-4 w-48 bg-muted animate-pulse rounded" />
      <div className="h-3 w-full bg-muted animate-pulse rounded" />
      <div className="h-3 w-3/4 bg-muted animate-pulse rounded" />
      <div className="h-3 w-5/6 bg-muted animate-pulse rounded" />
      <div className="h-20 w-full bg-muted animate-pulse rounded mt-2" />
    </div>
  );
}

function ActiveSection({
  sectionId,
  courseId,
  reviewEnabled,
  aiActionsEnabled,
}: {
  sectionId: SectionId;
  courseId: string;
  reviewEnabled: boolean;
  aiActionsEnabled: boolean;
}) {
  switch (sectionId) {
    case "notes":
      return <NotesSection courseId={courseId} aiActionsEnabled={aiActionsEnabled} />;
    case "practice":
      return <PracticeSection courseId={courseId} showReview={reviewEnabled} aiActionsEnabled={aiActionsEnabled} />;
    case "analytics":
      return <AnalyticsSection courseId={courseId} />;
    case "plan":
      return <PlanSection courseId={courseId} aiActionsEnabled={aiActionsEnabled} />;
    default:
      return <NotesSection courseId={courseId} aiActionsEnabled={aiActionsEnabled} />;
  }
}

export function SectionContainer({
  courseId,
  reviewEnabled,
  aiActionsEnabled = true,
  visibleSections,
}: SectionContainerProps) {
  const activeSection = useWorkspaceStore((s) => s.activeSection);
  const setActiveSection = useWorkspaceStore((s) => s.setActiveSection);
  const pdfOverlay = useWorkspaceStore((s) => s.pdfOverlay);

  const tabs = visibleSections
    ? SECTIONS.filter((s) => visibleSections.includes(s.id))
    : SECTIONS;

  return (
    <div
      className="flex-1 flex flex-col min-h-0 overflow-hidden bg-[var(--section-bg)]"
      data-testid="section-container"
    >
      {/* Horizontal scrollable tab bar */}
      <div
        className="shrink-0 flex items-center gap-1 border-b overflow-x-auto scrollbar-none px-2 py-1 touch-pan-x"
      >
        {tabs.map((tab) => (
          <button
            type="button"
            key={tab.id}
            data-testid={`section-tab-${tab.id}`}
            onClick={() => setActiveSection(tab.id)}
            className={cn(
              "shrink-0 px-3 py-1 text-xs font-medium rounded-md transition-colors whitespace-nowrap",
              activeSection === tab.id
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-muted",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Section content */}
      {pdfOverlay ? (
        <PdfViewerOverlay courseId={courseId} />
      ) : (
        <Suspense fallback={<SectionSkeleton />}>
          <ActiveSection
            sectionId={activeSection}
            courseId={courseId}
            reviewEnabled={reviewEnabled}
            aiActionsEnabled={aiActionsEnabled}
          />
        </Suspense>
      )}
    </div>
  );
}
