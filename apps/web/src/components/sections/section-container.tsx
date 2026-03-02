"use client";

import { Suspense, lazy } from "react";
import { useWorkspaceStore, type SectionId } from "@/store/workspace";
import { SectionSelector } from "./section-selector";
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
}

/** Loading skeleton shown while a section chunk is being fetched. */
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

/** Map section id to its lazily-loaded component. */
function ActiveSection({ sectionId, courseId }: { sectionId: SectionId; courseId: string }) {
  switch (sectionId) {
    case "notes":
      return <NotesSection courseId={courseId} />;
    case "practice":
      return <PracticeSection courseId={courseId} />;
    case "analytics":
      return <AnalyticsSection courseId={courseId} />;
    case "plan":
      return <PlanSection courseId={courseId} />;
    default:
      return <NotesSection courseId={courseId} />;
  }
}

/**
 * Main section container.
 *
 * Renders the right-side workspace section panel with:
 * - A header bar containing the section dropdown selector (left) and action area (right)
 * - The currently active section component, dynamically imported
 * - A PDF viewer overlay that replaces the section content when a PDF is open
 */
export function SectionContainer({ courseId }: SectionContainerProps) {
  const activeSection = useWorkspaceStore((s) => s.activeSection);
  const pdfOverlay = useWorkspaceStore((s) => s.pdfOverlay);

  return (
    <div
      className="flex-1 flex flex-col overflow-hidden bg-[var(--section-bg)]"
      data-testid="section-container"
    >
      {/* Header bar */}
      <div className="px-2 py-1 border-b flex items-center gap-2 shrink-0 bg-[var(--section-header)]">
        <SectionSelector />
        {/* Action buttons slot -- section-specific actions can be added here */}
        <div className="ml-auto flex items-center gap-1" />
      </div>

      {/* Content area */}
      {pdfOverlay ? (
        <PdfViewerOverlay courseId={courseId} />
      ) : (
        <Suspense fallback={<SectionSkeleton />}>
          <ActiveSection sectionId={activeSection} courseId={courseId} />
        </Suspense>
      )}
    </div>
  );
}
