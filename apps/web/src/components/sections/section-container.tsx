"use client";

import { Suspense, lazy } from "react";
import { Button } from "@/components/ui/button";
import { useWorkspaceStore, type SectionId } from "@/store/workspace";
import { SECTIONS } from "@/lib/constants";
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
  visibleSections: SectionId[];
  chatEnabled: boolean;
  reviewEnabled: boolean;
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
}: {
  sectionId: SectionId;
  courseId: string;
  reviewEnabled: boolean;
}) {
  switch (sectionId) {
    case "notes":
      return <NotesSection courseId={courseId} />;
    case "practice":
      return <PracticeSection courseId={courseId} showReview={reviewEnabled} />;
    case "analytics":
      return <AnalyticsSection courseId={courseId} />;
    case "plan":
      return <PlanSection courseId={courseId} />;
    default:
      return <NotesSection courseId={courseId} />;
  }
}

export function SectionContainer({
  courseId,
  visibleSections,
  chatEnabled,
  reviewEnabled,
}: SectionContainerProps) {
  const activeSection = useWorkspaceStore((s) => s.activeSection);
  const pdfOverlay = useWorkspaceStore((s) => s.pdfOverlay);
  const setActiveSection = useWorkspaceStore((s) => s.setActiveSection);

  return (
    <div
      className="flex-1 flex flex-col overflow-hidden bg-[var(--section-bg)]"
      data-testid="section-container"
    >
      <div className="px-2 py-1 border-b flex items-center gap-2 shrink-0 bg-[var(--section-header)]">
        <SectionSelector visibleSections={visibleSections} />
        <div className="ml-auto flex items-center gap-1">
          {SECTIONS.filter((s) =>
            visibleSections.includes(s.id),
          ).map((s) => (
            <Button
              key={s.id}
              type="button"
              variant={activeSection === s.id ? "secondary" : "ghost"}
              size="sm"
              className="h-7 px-2 text-xs"
              title={s.label}
              onClick={() => setActiveSection(s.id)}
            >
              {s.label}
            </Button>
          ))}
          {chatEnabled ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              title="Chat"
              onClick={() => {
                document
                  .querySelector<HTMLTextAreaElement>("[data-chat-input]")
                  ?.focus();
              }}
            >
              Chat
            </Button>
          ) : null}
        </div>
      </div>

      {pdfOverlay ? (
        <PdfViewerOverlay courseId={courseId} />
      ) : (
        <Suspense fallback={<SectionSkeleton />}>
          <ActiveSection
            sectionId={activeSection}
            courseId={courseId}
            reviewEnabled={reviewEnabled}
          />
        </Suspense>
      )}
    </div>
  );
}
